# Copyright 2023 Daniel Vallance
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


import argparse

import traceback

from get_yaml_dict import get_yaml_dict
import math
import socket
import sys
import time
import asyncio
from ReceivedAppData import ReceivedAppData
from ForwardingEntry import ForwardingEntry
from RemoteLocEntry import RemoteLocEntry
from AvailableRouterEntry import AvailableRouterEntry
from utilities import *
from ipv4_control_utilities import *
from regular_coroutines import *
from mgmt_utilities import *
from UnackedLU import UnackedLU
from OwnLocEntry import OwnLocEntry
import os
from resource_getters import *


class EmulatedIoT:

    """
    Object representing the emulated IoT devices
    """
    def __init__(self, no_inv_locs, net_protocol, **kwargs):

        # Dictionary that maps locator values to DatagramEndpoints which are bound to the corresponding multicast group
        self.loc_transports = {}
        self.is_router = no_inv_locs != -1
        self.net_protocol = net_protocol

        # Reference to the running process that psutil can use
        self.process = get_process()

        # Initialise list of invariant locators (will not change throughout run)
        if self.is_router:
            self.inv_locs = get_locators(no_inv_locs)
        else:
            self.inv_locs = []

        # Number of next advertisement and solicitations to be sent
        self.router_ad_no = 0
        self.neighbour_ad_no = 0
        self.neighbour_sol_no = 0
        self.router_sol_no = 0

        # Latest advertisements and solicitations seen from other nodes
        self.latest_router_ads = {}
        self.latest_router_sols = {}
        self.latest_neighbour_sols = {}
        self.ilv_na = {}
        self.id_na = {}

        # Next transport flood to be sent
        self.flood_no = 1

        # Latest flood from other nodes seen
        self.floods_seen = {}


        self.device_id = get_identifier()

        # Transport ports
        self.port_qs = {}
        self.port_events = {}

        # Deficit round robin remote locator counters
        self.deficits = {}

        # State for routing and forwarding
        self.correspondents = {}
        self.ilv_cache = {}
        self.own_locs_cache = {}
        self.available_routers = {}
        self.routers_by_loc = {}
        self.forwarding_table = {}

        # Chronological order of current locator set
        self.loc_set_no = 0

        # Latest locator sets seen from other nodes
        self.loc_set_nos = {}

        self.unacked_lu = None

        # Cache of timed out locs which could not be subject to a hard handoff at that moment in time
        self.timed_out_aged_locs = set()
        self.has_unacked_lu = None

        # Overhead stats
        self.ilnp_dgrams_sent = 0
        self.app_dgrams_sent = 0
        self.app_bytes_sent = 0
        self.ilnp_bytes_sent = 0

        self.ilnp_dgrams_recvd = 0
        self.app_dgrams_recvd = 0
        self.app_bytes_recvd = 0
        self.ilnp_bytes_recvd = 0

        self.start_time = time.time()

        # Initialise state of settings dict
        # Learned to use setattr to do this here: https://stackoverflow.com/questions/8187082/how-can-you-set-class-attributes-from-variable-arguments-kwargs-in-python
        for key in kwargs:
            setattr(self, key, kwargs[key])

        self.written_back = False
        self.server_writer = None
        self.api_server_active = asyncio.Event()

        # Event indicating that a handoff is taking place
        self.handing_off = asyncio.Event()

        # If the emulated IoT is using IPv6, record most recently used source and destination locators for each destination ID to prevent multipath usage
        if self.net_protocol == NetProtocol.IPv6.value:
            self.ipv6_conn_maps = {}

    async def start_emulated_iot(self, **kwargs):
        """
        Start the asyncio tasks which comprise the emulated IoT
        """

        # Record if a writer is waiting for confirmation the emulated IoT has started
        if "writer" in kwargs:
            self.server_writer = kwargs["writer"]

        try:

            # Set default exception handler
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(self.handle_exception)


            self.has_unacked_lu = asyncio.Event()
            tasks = []

            # Get broadcast locator DatagramEndpoint
            self.loc_transports[self.BROADCAST_LOC] = await self.get_loc_transport(self.BROADCAST_LOC)

            # If it is a router, get a DatagramEndpoint for all its invariant locators, and initialise the task that broadcasts router advertisements
            if self.is_router:

                for loc in self.inv_locs:
                    self.loc_transports[loc] = await self.get_loc_transport(loc)

                tasks.append(asyncio.create_task(broadcast_router_ads(self)))

            # Initialise other tasks

            tasks.append(asyncio.create_task(flood_neighbour_ads(self)))

            tasks.append(asyncio.create_task(purge_correspondents(self)))

            tasks.append(asyncio.create_task(purge_ilv_cache(self)))

            tasks.append(asyncio.create_task(purge_own_locs(self)))

            tasks.append(asyncio.create_task(purge_available_routers(self)))

            tasks.append(asyncio.create_task(purge_forwarding_table(self)))

            tasks.append(asyncio.create_task(process_unacked_lu(self)))

            tasks.append(asyncio.create_task(api_server(self)))

            # Send solicitations task
            configure_task = asyncio.create_task(self.net_configuration())

            # Wait for the API server to become active and the self configuration to be performed
            await self.api_server_active.wait()
            await configure_task

            # Inform the writer that the emulated IoT is initialised
            if self.server_writer is not None:
                self.server_writer.write(int.to_bytes(0, 1, "little", signed=True))
                await self.server_writer.drain()
                self.written_back = True

            await asyncio.gather(*tasks)

        # Cancel the tasks and stop in the face of any exceptions
        except:
            await self.stop_emulated_iot()

    # Learend about exception handlers here
    # https://www.roguelynn.com/words/asyncio-exception-handling/
    def handle_exception(self, loop, context):
        # Stop the emulated IoT in the face of any exceptions
        print(context)
        asyncio.create_task(self.stop_emulated_iot())

    async def net_configuration(self):
        """
        Send neighbour and router solicitations to get connectivity information
        """
        rs = self.get_router_sol()
        ns = self.get_neighbour_sol(self.BROADCAST_IDENTIFIER)

        self.broadcast(rs, NextHeader.CONTROL.value)

        self.flood(ns, NextHeader.CONTROL.value, [])

        # Wait a configured amount for responses
        await asyncio.sleep(self.startup_wait)

    async def stop_emulated_iot(self, **kwargs):
        """
        Stop the emulated IoT by cancelling all tasks
        """
        # Learned to cancel all tasks here: https://superfastpython.com/asyncio-gather-cancel-all-if-one-fails/

        # If failed to initialise, inform writer that initialisation failed
        if not self.written_back and self.server_writer is not None:
            self.server_writer.write(int.to_bytes(-1, 1, "little", signed=True))
            await self.server_writer.drain()
            self.written_back = True

        cancelled_tasks = []

        tasks = asyncio.all_tasks()
        # get the current task
        current = asyncio.current_task()
        # remove current task from all tasks
        tasks.remove(current)
        # cancel all remaining running tasks
        for task in tasks:
            name = task.get_name()

            # Do not cancel these tasks
            if name == SERVER or name == HANDLER or name == RUNNER:
                continue
            task.cancel()
            cancelled_tasks.append(task)

        # Await the cancelled tasks
        for ct in cancelled_tasks:
            try:
                await ct
            except asyncio.exceptions.CancelledError as e:
                print(e)

        transports = list(self.loc_transports)

        # Close the DatagramEndpoints
        for transport in transports:
            self.loc_transports[transport].close()
            del self.loc_transports[transport]

        # unset exception handler
        asyncio.get_running_loop().set_exception_handler(None)

        # If a writer was passed in, inform that the emulated IoT was stopped successfully
        if "writer" in kwargs:
            kwargs["writer"].write(int.to_bytes(0, 1, "little", signed=True))
            await kwargs["writer"].drain()


    async def get_loc_transport(self, loc):
        """
        Get DatagramEndpoint for the passed locator
        """
        return await get_loc_transport(loc, self.mcast_prefix, self.process_dgram, self.FLOW_INFO, self.SCOPE_ID)


    async def join(self, locs):

        """
        Attempt to add the passed locs to the locator set
        """

        # Cannot have a locator update with more than max locs
        if len(locs) > self.max_locs:
            return False




        # Cannot perform a locator update if another one is ongoing
        if self.handing_off.is_set() or self.has_unacked_lu.is_set():
            return False

        self.handing_off.set()


        not_already_joined = {loc for loc in locs if
                              loc not in self.own_locs_cache and loc not in self.inv_locs and loc != self.BROADCAST_LOC}

        # Method is trivially successful if all the specified locators have already been joined
        if len(not_already_joined) == 0:
            self.handing_off.clear()
            return True

        available_locs = self.get_available_locs()

        to_join = not_already_joined.intersection(available_locs.keys())

        # If some specified locators are not available to join, fail
        if len(to_join) < len(not_already_joined):
            self.handing_off.clear()
            return False

        # Hard handoff if no correspondents or IPv6 is used
        if len(self.correspondents) == 0 or self.net_protocol == NetProtocol.IPv6.value:

            loc_transports_copy = self.loc_transports.copy()
            own_locs_cache_copy = self.own_locs_cache.copy()

            # Get the DatagramEndpoint for each locator and record it
            for loc in to_join:
                transport_loc = await self.get_loc_transport(loc)
                loc_transports_copy[loc] = transport_loc
                own_locs_cache_copy[loc] = OwnLocEntry(LocatorFlag.ACTIVE.value,
                                                       available_locs[loc] + self.own_loc_active_timeout)



            self.loc_transports = loc_transports_copy
            self.own_locs_cache = own_locs_cache_copy

            # Record that this is a new locator set
            self.loc_set_no += 1

        else:

            loc_transports_copy = self.loc_transports.copy()
            own_locs_cache_copy = self.own_locs_cache.copy()

            # Get the DatagramEndpoint for each locator
            for loc in to_join:
                transport_loc = await self.get_loc_transport(loc)
                loc_transports_copy[loc] = transport_loc
                own_locs_cache_copy[loc] = OwnLocEntry(LocatorFlag.VALID_JOIN.value,
                                                       available_locs[loc] + self.own_loc_active_timeout)

            self.loc_transports = loc_transports_copy
            self.own_locs_cache = own_locs_cache_copy

            # Get soft join locator update and send it to correspondents
            lu = self.get_locator_update(LUAction.ILNP_LU_ADD_SOFT.value, LUOperation.ILNP_LU_AD.value, to_join)
            self.unacked_lu = UnackedLU(lu, list(self.correspondents))
            self.has_unacked_lu.set()

            correspondents_copy = self.correspondents.copy()
            for correspondent in correspondents_copy:
                self.send(correspondent, lu, NextHeader.CONTROL.value)

        # Send neighbour advertisement (this acts as the hard join locator update if hard handoff was used)
        na = self.get_neighbour_ad()
        self.flood(na, NextHeader.CONTROL.value, [])

        # Neighbour solicitation to prompt connectivity
        ns = self.get_neighbour_sol(self.BROADCAST_IDENTIFIER)
        self.flood(ns, NextHeader.CONTROL.value, [])

        self.handing_off.clear()
        return True





    def leave(self, locs):
        """
        Attempts to remove passed locs from locator set
        """

        # Cannot use a locator update with more than max locs
        if len(locs) > self.max_locs:
            return False

        locs = set(locs)

        # Cannot leave invariant locators or the broadcast locator
        if locs.intersection({self.BROADCAST_LOC}.union(self.inv_locs)):
            return False

        # Cannot perform any handoff when handoff is currently being performed
        if self.unacked_lu is not None or self.has_unacked_lu.is_set():
            return False

        to_leave = locs.intersection(set(self.own_locs_cache))

        # Method trivially succeeds if there are no locators to leave
        if len(to_leave) == 0:
            return True

        # Just delete the DatagramEndpoints if using IPv6 or there are no correspondents
        if len(self.correspondents) == 0 or self.net_protocol == NetProtocol.IPv6.value:

            for loc in to_leave:
                self.delete_loc_transport(loc)

            self.loc_set_no += 1

        else:

            # Get soft locator update and send it to correspondents
            lu = self.get_locator_update(LUAction.ILNP_LU_DELETE_SOFT.value, LUOperation.ILNP_LU_AD.value,
                                         to_leave)
            self.unacked_lu = UnackedLU(lu, list(self.correspondents.keys()))
            self.has_unacked_lu.set()

            # Update own locator flags
            for loc in to_leave:
                self.own_locs_cache[loc] = OwnLocEntry(LocatorFlag.VALID_LEAVE.value, None)

            correspondents_copy = self.correspondents.copy()
            for correspondent in correspondents_copy:
                self.send(correspondent, lu, NextHeader.CONTROL.value)

        # Neighbour advertisement to advertise new locator set (also acts as hard locator update if that was used)
        na = self.get_neighbour_ad()
        self.flood(na, NextHeader.CONTROL.value, [])

        ns = self.get_neighbour_sol(self.BROADCAST_IDENTIFIER)
        self.flood(ns, NextHeader.CONTROL.value, [])

        return True

    async def replace(self, locs):

        """
        Replace replaceable locator set (ie locator set excluding broadcast locator and invariant locators) with passed set
        """

        # Cannot have more than max locs locators in a locator update
        if len(locs) > self.max_locs:
            return False

        # Cannot perform a handoff when one is currently being performed
        if self.handing_off.is_set() or self.has_unacked_lu.is_set():
            return False

        self.handing_off.set()

        # Get replaceable locator set
        locs = set(locs) - set(self.inv_locs).union({self.BROADCAST_LOC})

        current_locs = set(self.own_locs_cache)

        not_already_joined = set(locs) - set(current_locs)

        not_already_left = set(current_locs) - set(locs)

        # Method trivially succeeds if no changes are required
        if len(not_already_joined) == 0 and len(not_already_left) == 0:
            self.handing_off.clear()
            return True

        to_leave = not_already_left

        available_locs = self.get_available_locs()

        to_join = not_already_joined.intersection(available_locs)

        # Fail if attempting to join unavailable locators
        if len(to_join) < len(not_already_joined):
            self.handing_off.clear()
            return False

        # Use hard handoff if no correspondents or using IPv6
        if len(self.correspondents) == 0 or self.net_protocol == NetProtocol.IPv6.value:

            loc_transports_copy = self.loc_transports.copy()
            own_locs_cache_copy = self.own_locs_cache.copy()

            # Create DatagramEndpoints for each locator being joined
            for loc in to_join:
                transport_loc = await self.get_loc_transport(loc)
                loc_transports_copy[loc] = transport_loc
                own_locs_cache_copy[loc] = OwnLocEntry(LocatorFlag.ACTIVE.value,
                                                       available_locs[loc] + self.own_loc_active_timeout)

            self.loc_transports = loc_transports_copy
            self.own_locs_cache = own_locs_cache_copy

            # Delete every locator being left
            for loc in to_leave:
                self.delete_loc_transport(loc)

            self.loc_set_no += 1

        # Soft handoff
        else:

            loc_transports_copy = self.loc_transports.copy()
            own_locs_cache_copy = self.own_locs_cache.copy()

            # Get DatagramEndpoint for every locator being joined
            for loc in to_join:
                transport_loc = await self.get_loc_transport(loc)
                loc_transports_copy[loc] = transport_loc
                own_locs_cache_copy[loc] = OwnLocEntry(LocatorFlag.VALID_JOIN.value,
                                                       available_locs[loc] + self.own_loc_active_timeout)

            self.loc_transports = loc_transports_copy
            self.own_locs_cache = own_locs_cache_copy

            # Change flag of locators being left
            for loc in to_leave:
                self.own_locs_cache[loc] = OwnLocEntry(LocatorFlag.VALID_LEAVE.value, None)

            # Send locator update to correspondents containing new locator set
            lu = self.get_locator_update(LUAction.ILNP_LU_REPLACE_SOFT.value, LUOperation.ILNP_LU_AD.value,
                                         set(self.inv_locs).union(current_locs).union(to_join) - to_leave)
            self.unacked_lu = UnackedLU(lu, list(self.correspondents))
            self.has_unacked_lu.set()

            correspondents_copy = self.correspondents.copy()
            for correspondent in correspondents_copy:
                self.send(correspondent, lu, NextHeader.CONTROL.value)

        # Flooding of neighbour advertisement makes sending hard locator update unnecessary
        na = self.get_neighbour_ad()
        self.flood(na, NextHeader.CONTROL.value, [])

        ns = self.get_neighbour_sol(self.BROADCAST_IDENTIFIER)
        self.flood(ns, NextHeader.CONTROL.value, [])

        self.handing_off.clear()
        return True


    def get_available_locs(self):
        """Get locators which are likely accessible as they have been recently advertised in a router advertisement"""

        locs = {}

        for router_id in self.available_routers:

            for loc in self.available_routers[router_id].locs:
                locs[loc] = self.available_routers[router_id].timeout

        return locs

    def delete_loc_transport(self, loc):
        """
        Delete DatagramEndpoint and entry of a locator
        """
        self.loc_transports[loc].close()
        del self.loc_transports[loc]
        del self.own_locs_cache[loc]

    def send(self, dst_id, payload, next_hdr, **kwargs):
        """
        Unicast send to dst_id
        """

        # Call the self_send method if sending to itself
        if dst_id == self.device_id:

            if "routing_prefix" in kwargs:
                return self.self_send(payload, next_hdr, routing_prefix=kwargs["routing_prefix"])
            else:
                return self.self_send(payload, next_hdr)

        # Fail if there is no record of which locators it is associated with
        if dst_id not in self.ilv_cache:
            return False

        # Cannot used AGED locs
        remote_locs = {loc for loc in self.ilv_cache[dst_id] if
                       self.ilv_cache[dst_id][loc].flag != LocatorFlag.AGED.value}

        # If all their locs are AGED, fail
        if len(remote_locs) == 0:
            return False

        own_usable_locs = self.get_own_usable_locs()

        available_next_hops = self.get_available_next_hops(own_usable_locs)

        # Get locators which can be forwarded to
        forwardable_dst_locs = {loc for loc in self.forwarding_table if
                                available_next_hops.intersection(
                                    {forwarding_entry.device_id for forwarding_entry in
                                     self.forwarding_table[loc]})}

        # Get non-aged remote locs that can be forwarded to
        reachable_dst_locs = forwardable_dst_locs.union(own_usable_locs).intersection(remote_locs)

        if len(reachable_dst_locs) == 0:
            return False

        # ILNP chooses which of these locators to choose in a deficit round robin fashion
        if self.net_protocol == NetProtocol.ILNP.value:
            chosen_dst_loc = self.choose_loc(dst_id, reachable_dst_locs,
                                             len(payload) + HeaderSizes["ILNP"] + HeaderSizes["LINK"])

        # IPv6 uses the previous source and destination locators it used (unless otherwise specified)
        # If these are no longer valid, arbitrarily choose them and record them to be used next time
        else:
            if "routing_prefix" in kwargs:

                if kwargs["routing_prefix"] not in reachable_dst_locs:
                    return False

                chosen_dst_loc = kwargs["routing_prefix"]

            elif dst_id not in self.ipv6_conn_maps or self.ipv6_conn_maps[dst_id][0] not in reachable_dst_locs:
                chosen_dst_loc = list(reachable_dst_locs)[0]

            else:
                chosen_dst_loc = self.ipv6_conn_maps[dst_id][0]

            if self.ipv6_conn_maps.get(dst_id, (None, None))[0] is None or chosen_dst_loc != self.ipv6_conn_maps.get(dst_id, (None, None))[0]:
                self.ipv6_conn_maps[dst_id] = (chosen_dst_loc, None)

        # Get the next hop
        next_id, next_loc = self.get_next_hop(dst_id, chosen_dst_loc, available_next_hops, own_usable_locs)

        if self.net_protocol == NetProtocol.IPv6.value:
            self.ipv6_conn_maps[dst_id] = (chosen_dst_loc, next_loc)

        # Package the data and send it
        ilnp_dgram = self.get_ilnp_dgram(next_hdr, next_loc, dst_id, chosen_dst_loc, payload)

        link_frame = self.get_link_frame(next_id, next_loc, ilnp_dgram)

        if not self.transmit(link_frame):
            return False

        if next_hdr == NextHeader.TRANSPORT.value:
            self.app_dgrams_sent += 1
            self.app_bytes_sent += (len(payload) - HeaderSizes["TRANSPORT"])

        return True




    def get_next_hop(self, dst_id, dst_loc, available_next_hops, own_usable_locs):
        """
        Gets next hop to the destination identifier and locator
        """

        # Fail if the emulated IoT has no usable locators
        if not own_usable_locs:
            return None, None

        # IPv6 should attempt to use the existing connection
        if self.net_protocol == NetProtocol.IPv6.value and self.ipv6_conn_maps.get(dst_id,(None,None))[1] is not None:
            conn_src_loc = self.ipv6_conn_maps[dst_id][1]
            if conn_src_loc in own_usable_locs:
                conn_src_loc_routers = self.routers_by_loc.get(conn_src_loc)
                conn_next_hops = [fwd_entry.device_id for fwd_entry in self.forwarding_table.get(dst_loc,[]) if
                                           fwd_entry.device_id in conn_src_loc_routers]

                if conn_next_hops:
                    return conn_next_hops[0], conn_src_loc

        # Send directly if source and destination in same locator
        if dst_loc in own_usable_locs:
            next_id = dst_id
            next_loc = dst_loc

        else:
            # fail if no forwarding table entry
            if dst_loc not in self.forwarding_table:
                return None, None

            potential_next_hops = [fwd_entry for fwd_entry in self.forwarding_table[dst_loc] if
                                   fwd_entry.device_id in available_next_hops]

            if not potential_next_hops:
                return None, None

            # next hop id chosen arbitrarily from valid options
            next_id = potential_next_hops[0].device_id

            # get locators which it shares with the next_id and that are not AGED
            potential_next_locs = [loc for loc in self.ilv_cache[next_id] if
                                   self.ilv_cache[next_id][loc].flag in [LocatorFlag.ACTIVE.value,
                                                                         LocatorFlag.EXPIRED.value] and loc in own_usable_locs]

            # next loc chosen arbitrarily from valid options
            next_loc = potential_next_locs[0]

        return next_id, next_loc

    def self_send(self, payload, next_hdr, **kwargs):
        """
        Sends to itself
        """

        own_usable_locs = self.get_own_usable_locs()

        if len(own_usable_locs) == 0:
            return False

        # IPv6 will try and use the last used locator to maintain a connection unless otherwise specified
        if "routing_prefix" in kwargs:

            if kwargs["routing_prefix"] not in own_usable_locs:
                return False

            chosen_dst_loc = kwargs["routing_prefix"]

        elif self.net_protocol == NetProtocol.IPv6.value and (self.device_id in self.ipv6_conn_maps and self.ipv6_conn_maps[self.device_id][0] in own_usable_locs):
            chosen_dst_loc = self.ipv6_conn_maps[self.device_id][0]
        # ILNP will use any of its own locs
        else:
            chosen_dst_loc = list(own_usable_locs)[0]

        # Record connection used if using IPv6
        if self.net_protocol == NetProtocol.IPv6.value:
            self.ipv6_conn_maps[self.device_id] = (chosen_dst_loc, chosen_dst_loc)

        # Package and transmit
        ilnp_dgram = self.get_ilnp_dgram(next_hdr, chosen_dst_loc, self.device_id, chosen_dst_loc, payload)

        link_frame = self.get_link_frame(self.device_id, chosen_dst_loc, ilnp_dgram)

        if self.transmit(link_frame):
            if next_hdr == NextHeader.TRANSPORT.value:
                self.app_dgrams_sent += 1
                self.app_bytes_sent += (len(payload) - HeaderSizes["TRANSPORT"])
            return True
        else:
            return False

    def choose_loc(self, dst_id, locs, payload_len):
        """
        Deficit Round Robin choosing of a locator
        """

        # Learned about the deficit round robin algorithm here: https://studres.cs.st-andrews.ac.uk/CS4105/Lectures/wk03/cs4105-network_traffic.pdf

        # Initialise deficits to 0 if not already present
        for loc in locs:
            if (dst_id, loc) not in self.deficits:
                self.deficits[(dst_id, loc)] = 0

        # DRR algorithm
        for i in range(math.ceil(payload_len / self.QUANTUM)):
            for loc in locs:

                c = self.QUANTUM + self.deficits[(dst_id, loc)]
                if payload_len <= c:
                    self.deficits[(dst_id, loc)] = c - payload_len
                    return loc

                self.deficits[(dst_id, loc)] += self.QUANTUM

    def get_own_usable_locs(self):
        """
        Get own locs which are not AGED and not the broadcast locator
        """

        return {loc for loc in self.loc_transports if
                loc in self.inv_locs or (
                        loc in self.own_locs_cache and self.own_locs_cache[loc].flag in [LocatorFlag.ACTIVE.value,
                                                                                        LocatorFlag.VALID_JOIN.value,
                                                                                        LocatorFlag.VALID_LEAVE.value
                                                                                         ])}

    def get_available_next_hops(self, usable_locs):

        """
        Get the routers which are associated with any of the locators passed
        """

        available_next_hops = set()

        for loc in usable_locs:
            available_next_hops.update(self.routers_by_loc.get(loc, []))

        return available_next_hops

    def forward(self, ilnp_dgram):

        """
        Forward passed ILNP datagram towards destination
        """

        decoded_ilnp_dgram = decode_ilnp_dgram(ilnp_dgram)

        own_usable_locs = self.get_own_usable_locs()

        available_next_hops = self.get_available_next_hops(own_usable_locs)

        # Get next hop
        next_hop_id, next_loc = self.get_next_hop(decoded_ilnp_dgram["dst_id"], decoded_ilnp_dgram["dst_loc"],
                                                  available_next_hops, own_usable_locs)

        # Fail if could not find next hop, otherwise transmit
        if next_hop_id is None or next_loc is None:
            return False
        else:
            link_frame = self.get_link_frame(next_hop_id, next_loc, ilnp_dgram)

            return self.transmit(link_frame)


    # Methods for creating datagrams follow

    def get_router_ad(self):

        ra = get_router_ad(self.inv_locs, self.router_ad_no, self.device_id)
        self.router_ad_no += 1
        return ra

    def get_router_sol(self):
        rs = get_router_sol(self.router_sol_no)
        self.router_sol_no += 1
        return rs

    def get_neighbour_sol(self, neighbour_id):
        ns = get_neighbour_sol(neighbour_id, self.neighbour_sol_no)
        self.neighbour_sol_no += 1
        return ns

    def get_ilnp_dgram(self, next_hdr, src_loc, dst_id, dst_loc, payload):
        return get_ilnp_dgram(next_hdr, self.device_id, src_loc, dst_id, dst_loc, payload, self.is_router)

    def get_link_frame(self, dst_id, loc, payload):

        return get_link_frame(self.device_id, dst_id, loc, payload)

    def get_neighbour_ad(self):
        self.neighbour_ad_no += 1
        return get_neighbour_ad(self.get_own_usable_locs(), self.neighbour_ad_no, self.device_id, self.is_router,
                                self.loc_set_no)

    def flood(self, payload, payload_type, exceptions):
        """
        Floods the payload across the network
        """

        success = True

        for loc in self.get_own_usable_locs():
            if loc in exceptions:
                continue

            # Package and transmit
            ilnp_dgram = self.get_ilnp_dgram(payload_type, loc, self.BROADCAST_IDENTIFIER, self.BROADCAST_LOC, payload)
            link_frame = self.get_link_frame(self.BROADCAST_IDENTIFIER, loc, ilnp_dgram)
            if not self.transmit(link_frame):
                success = False

        if success:
            if payload_type == NextHeader.TRANSPORT.value:
                self.app_dgrams_sent += 1
                self.app_bytes_sent += (len(payload) - HeaderSizes["TRANSPORT"])

        return success

    def get_transport_dgram(self, src_port, dst_port, payload, flood):
        """
        Converts payload into several transport dgrams which will be lower than the MSS
        """
        dgrams = []

        for i in range(0, len(payload), self.transport_mss):
            if flood:
                dgrams.append(get_transport_dgram(src_port, dst_port, self.flood_no, payload[i:i+self.transport_mss]))
                self.flood_no += 1
            else:
                dgrams.append(get_transport_dgram(src_port, dst_port, 0, payload[i:i+self.transport_mss]))

        return dgrams

    def forward_flood(self, ilnp_dgram, exceptions):
        """
        Forwards a flood
        """

        success = True

        for loc in self.get_own_usable_locs():
            if loc in exceptions:
                continue

            # Package and transmit
            link_frame = self.get_link_frame(self.BROADCAST_IDENTIFIER, loc, ilnp_dgram)
            if not self.transmit(link_frame):
                success = False

        return success

    def broadcast(self, payload, payload_type):
        """
        Sends a payload on the broadcast locator
        """

        # Package and transmit
        ilnp_dgram = self.get_ilnp_dgram(payload_type, self.BROADCAST_LOC, self.BROADCAST_IDENTIFIER,
                                         self.BROADCAST_LOC, payload)
        link_frame = self.get_link_frame(self.BROADCAST_IDENTIFIER, self.BROADCAST_LOC, ilnp_dgram)
        if self.transmit(link_frame):
            if payload_type == NextHeader.TRANSPORT.value:
                self.app_dgrams_sent += 1
                self.app_bytes_sent += (len(payload) - HeaderSizes["TRANSPORT"])
            return True
        else:
            return False

    def get_locator_update(self, action, op, locs):
        return get_locator_update(action, op, locs, self.loc_set_no + 1, self.device_id)

    def record_forwarding_path(self, dst_loc, next_hop_id, hops):
        """
        Encodes that the passed locator is reachable through the next hop passed in the number of hops
        passed in the forwarding table
        """

        entry = ForwardingEntry(next_hop_id, hops, time.time() + self.forwarding_entry_timeout)

        # Initialise the entry for the destination locator if it does not exist
        if dst_loc not in self.forwarding_table:
            self.forwarding_table[dst_loc] = [entry]

        # Otherwise add the entry, while filtering out other entries which are older and use the same next hop with more hops
        else:
            self.forwarding_table[dst_loc] = [fwd_entry for fwd_entry in self.forwarding_table[dst_loc]
                                              if
                                              fwd_entry.device_id != next_hop_id or fwd_entry.hops < hops]

            self.forwarding_table[dst_loc].append(entry)

            # Sort by number of hops
            self.forwarding_table[dst_loc].sort()

    def transmit(self, link_frame):

        """
        Send the link frame on the appropriate multicast group
        """

        decoded_link_frame = decode_link_frame(link_frame)
        decoded_ilnp_dgram = decode_ilnp_dgram(decoded_link_frame["payload"])

        dst_loc = decoded_link_frame["loc"]

        # Fail if there is no DatagramEndpoint for this locator
        if dst_loc not in self.loc_transports:
            return False

        # Send link frame to appropriate multicast group from appropriate DatagramEndpoint
        self.loc_transports[dst_loc].sendto(link_frame,
                                            (locator_to_mcast(dst_loc, self.mcast_prefix), self.emulation_port, self.FLOW_INFO,
                                             self.SCOPE_ID))

        # If using link frame unicast, add destination as a correspondent
        if decoded_link_frame["dst_id"] != self.BROADCAST_IDENTIFIER:
            self.correspondents[decoded_link_frame["dst_id"]] = time.time() + self.correspondents_timeout

        # If using ILNP unicast, add destination as a correspondent
        if decoded_ilnp_dgram["dst_id"] != self.BROADCAST_IDENTIFIER:
            self.correspondents[decoded_ilnp_dgram["dst_id"]] = time.time() + self.correspondents_timeout

        self.ilnp_dgrams_sent += 1
        self.ilnp_bytes_sent += len(decoded_link_frame["payload"])

        return True


    async def process_dgram(self, b):
        """
        Process datagrams from other emulated IoT devices
        """

        # Simulate delay
        await asyncio.sleep(self.delay)

        decoded_link_frame = decode_link_frame(b)

        # Drop link frames not intended for this emulated IoT
        if decoded_link_frame["dst_id"] not in [self.device_id, self.BROADCAST_IDENTIFIER]:
            return

        # Add the source as a correspondent if using unicast
        if decoded_link_frame["dst_id"] == self.device_id:
            self.correspondents[decoded_link_frame["src_id"]] = time.time() + self.correspondents_timeout

        decoded_ilnp_dgram = decode_ilnp_dgram(decoded_link_frame["payload"])


        # Update entry for source locator in ILV
        if decoded_ilnp_dgram["src_loc"] in self.ilv_cache.get(decoded_ilnp_dgram["src_id"], []):
            self.ilv_cache[decoded_ilnp_dgram["src_id"]][decoded_ilnp_dgram["src_loc"]].last_used = time.time()

            if self.ilv_cache[decoded_ilnp_dgram["src_id"]][
                decoded_ilnp_dgram["src_loc"]].flag == LocatorFlag.AGED.value:
                self.ilv_cache[decoded_ilnp_dgram["src_id"]][
                    decoded_ilnp_dgram["src_loc"]].flag = LocatorFlag.EXPIRED.value

                if decoded_ilnp_dgram["is_router"]:
                    self.routers_by_loc[decoded_ilnp_dgram["src_loc"]].update([decoded_ilnp_dgram["src_id"]])


        # If this ILNP packet is not meant for this node, forward it if it is a router, then return
        if decoded_ilnp_dgram["dst_id"] not in [self.device_id, self.BROADCAST_IDENTIFIER]:
            if self.is_router:
                self.forward(decoded_link_frame["payload"])
            return

        elif decoded_ilnp_dgram["dst_id"] == self.device_id:

            # Treat receiving datagram on locator that is the subject of a soft join or replace, as an acknowledgement
            if self.unacked_lu is not None and decoded_ilnp_dgram[
                "src_id"] in self.unacked_lu.outstanding_acks and self.own_locs_cache.get(
                decoded_ilnp_dgram["dst_loc"], -1) == LocatorFlag.VALID_JOIN.value:
                self.remove_outstanding_ack(decoded_ilnp_dgram["src_id"])

            self.correspondents[decoded_ilnp_dgram["src_id"]] = time.time() + self.correspondents_timeout

        self.ilnp_dgrams_recvd += 1
        self.ilnp_bytes_recvd += len(decoded_link_frame["payload"])

        # Handle transport data
        if decoded_ilnp_dgram["next_hdr"] == NextHeader.TRANSPORT.value:

            decoded_transport_dgram = decode_transport_dgram(decoded_ilnp_dgram["payload"])

            if decoded_ilnp_dgram["dst_id"] == self.BROADCAST_IDENTIFIER:

                if decoded_ilnp_dgram["src_id"] == self.device_id:
                    # Ignore floods which originated from this device
                    return

                # Ignore seen floods and record this flood has been seen
                if decoded_ilnp_dgram["src_id"] not in self.floods_seen:
                    self.floods_seen[decoded_ilnp_dgram["src_id"]] = {decoded_transport_dgram["flood_no"]}
                else:
                    if decoded_transport_dgram["flood_no"] in self.floods_seen[decoded_ilnp_dgram["src_id"]]:
                        return
                    else:
                        self.floods_seen[decoded_ilnp_dgram["src_id"]].add(decoded_transport_dgram["flood_no"])

                # Forward flood if this is a router
                if self.is_router:
                    self.forward_flood(decoded_link_frame["payload"], [decoded_link_frame["loc"]])


            # Do not return as data if the port is not open
            if decoded_transport_dgram["dst_port"] not in self.port_qs:
                return

            # Place data on transport queue
            self.port_qs[decoded_transport_dgram["dst_port"]].put(b)

            self.app_dgrams_recvd += 1
            self.app_bytes_recvd += len(decoded_ilnp_dgram["payload"]) - HeaderSizes["TRANSPORT"]


            self.port_events[decoded_transport_dgram["dst_port"]].set()

        # Handle control packets
        elif decoded_ilnp_dgram["next_hdr"] == NextHeader.CONTROL.value:

            # Handle neighbour ads
            if decoded_ilnp_dgram["payload"][0] == ControlPacketType.NEIGHBOUR_AD.value:

                decoded_neighbour_ad = decode_neighbour_ad(decoded_ilnp_dgram["payload"])

                if decoded_neighbour_ad["id"] == self.device_id:
                    # ignore own neighbour ads
                    return

                neighbour_id = decoded_neighbour_ad["id"]

                ilv = (neighbour_id, decoded_ilnp_dgram["src_loc"])

                # If this neighbour ad is the most recent one from this node
                if decoded_neighbour_ad["ad_no"] > self.id_na.get(neighbour_id, -1):

                    # If this neighbour ad contains a more recent locator set number, update record of most recent locator set number
                    if decoded_neighbour_ad["loc_set_no"] > self.loc_set_nos.get(neighbour_id, -1):

                        self.loc_set_nos[decoded_neighbour_ad["id"]] = decoded_neighbour_ad["loc_set_no"]

                    # If emulation has record of a more recent locator set number from that node, ignore this ad
                    elif decoded_neighbour_ad["loc_set_no"] < self.loc_set_nos[neighbour_id]:
                        return

                    self.id_na[neighbour_id] = decoded_neighbour_ad["ad_no"]

                    # Remove the sender from all entries in routers by loc (will be readded later)
                    for loc in self.ilv_cache.get(decoded_neighbour_ad["id"], []):
                        if decoded_neighbour_ad["id"] in self.routers_by_loc.get(loc, {}):
                            self.routers_by_loc[loc].remove(decoded_neighbour_ad["id"])


                    # rewrite sender's entry in ilv cache
                    self.ilv_cache[neighbour_id] = {}

                    now = time.time()
                    for loc in decoded_neighbour_ad["locs"]:

                        self.ilv_cache[neighbour_id][loc] = RemoteLocEntry(LocatorFlag.ACTIVE.value,
                                                                           now + self.remote_loc_active_timeout,
                                                                           now)

                        # if sender is a router, add it to routers by loc and add forwarding path entry for all its locators
                        if decoded_neighbour_ad["is_router"]:
                            self.ilv_na[(neighbour_id, loc)] = decoded_neighbour_ad["ad_no"]
                            if loc not in self.routers_by_loc:
                                self.routers_by_loc[loc] = set()
                            self.routers_by_loc[loc].update([neighbour_id])
                            self.record_forwarding_path(loc, decoded_link_frame["src_id"],
                                                        decoded_neighbour_ad["hops"] + 1)

                    # forward neighbour ad if it is being flooded
                    if decoded_ilnp_dgram["dst_id"] == self.BROADCAST_IDENTIFIER and self.is_router and \
                            decoded_neighbour_ad["is_router"]:
                        ba = bytearray(decoded_link_frame["payload"])
                        ba[44:46] = int.to_bytes(decoded_neighbour_ad["hops"] + 1, 2, "little")
                        self.forward_flood(bytes(ba), [decoded_link_frame["loc"]])



                # If this neighbour ad is new for this ilv
                if decoded_neighbour_ad["ad_no"] > self.ilv_na.get(ilv, -1):

                    self.ilv_na[ilv] = decoded_neighbour_ad["ad_no"]

                    # record forwarding path if sender is not a router (as if it is a router it has already been recorded)
                    if not decoded_neighbour_ad["is_router"]:
                        self.record_forwarding_path(decoded_ilnp_dgram["src_loc"], decoded_link_frame["src_id"],
                                                    decoded_neighbour_ad["hops"] + 1)

                    # forward neighbour ad
                    if decoded_ilnp_dgram["dst_id"] == self.BROADCAST_IDENTIFIER and self.is_router:
                        ba = bytearray(decoded_link_frame["payload"])
                        ba[44:46] = int.to_bytes(decoded_neighbour_ad["hops"] + 1, 2, "little")
                        self.forward_flood(bytes(ba), [decoded_link_frame["loc"]])

            # Handles router ads
            elif decoded_ilnp_dgram["payload"][0] == ControlPacketType.ROUTER_AD.value:

                decoded_router_ad = decode_router_ad(decoded_ilnp_dgram["payload"])

                if decoded_router_ad["id"] == self.device_id:
                    # ignore own router ads
                    return

                # record ad no if this is the most recent router ad and ignore old router ads
                if decoded_router_ad["ad_no"] > self.latest_router_ads.get(decoded_router_ad["id"], -1):
                    self.latest_router_ads[decoded_router_ad["id"]] = decoded_router_ad["ad_no"]
                else:

                    return

                now = time.time()

                # record that this router and its invariant locators are available
                self.available_routers[decoded_router_ad["id"]] = AvailableRouterEntry(
                    decoded_router_ad["locs"], now + self.available_router_timeout)


                # Update timeouts and flags of own locators
                for loc in decoded_router_ad["locs"]:

                    if loc not in self.own_locs_cache:

                        continue
                    if self.own_locs_cache[loc].flag in [LocatorFlag.AGED.value, LocatorFlag.ACTIVE.value]:

                        self.own_locs_cache[loc].flag = LocatorFlag.ACTIVE.value
                        self.own_locs_cache[loc].timeout = now + self.own_loc_active_timeout
                    elif self.own_locs_cache[loc].flag == LocatorFlag.VALID_JOIN.value:
                        self.own_locs_cache[loc].timeout = now + self.own_loc_active_timeout


            # Handle locator update
            elif decoded_ilnp_dgram["payload"][0] == ControlPacketType.LOCATOR_UPDATE.value:

                decoded_locator_update = decode_locator_update(decoded_ilnp_dgram["payload"])

                if decoded_locator_update["operation"] == LUOperation.ILNP_LU_ACK.value:

                    # Ignore acknowledgement if not expecting the acknowledgement of that locator set number from that node
                    if self.unacked_lu is None or decoded_locator_update["loc_set_no"] != self.unacked_lu.decoded_lu[
                        "loc_set_no"] or decoded_ilnp_dgram["src_id"] not in self.unacked_lu.outstanding_acks:
                        return

                    # Otherwise accept acknowledgement
                    self.remove_outstanding_ack(decoded_ilnp_dgram["src_id"])

                # If not a locator update acknowledgment but just a locator update, process it
                else:
                    self.process_lu(decoded_ilnp_dgram["payload"], decoded_ilnp_dgram["is_router"])

            # Handle router solicitation
            elif decoded_ilnp_dgram["payload"][0] == ControlPacketType.ROUTER_SOL.value:

                decoded_router_sol = decode_router_sol(decoded_ilnp_dgram["payload"])

                # if this is not a router or this is an old router solicitation ignore it
                if not self.is_router or self.latest_router_sols.get(decoded_ilnp_dgram["src_id"], -1) >= decoded_router_sol[
                    "router_sol_no"]:
                    return

                self.latest_router_sols[decoded_ilnp_dgram["src_id"]] = decoded_router_sol["router_sol_no"]

                # broadcast router ad
                ra = self.get_router_ad()
                self.broadcast(ra, NextHeader.CONTROL.value)

            # Handle neighbour solicitation
            elif decoded_ilnp_dgram["payload"][0] == ControlPacketType.NEIGHBOUR_SOL.value:
                decoded_neigbour_sol = decode_neighbour_sol(decoded_ilnp_dgram["payload"])

                #ignore old neighbour solicitations
                if self.latest_neighbour_sols.get(decoded_ilnp_dgram["src_id"], -1) >= decoded_neigbour_sol[
                    "neighbour_sol_no"]:
                    return

                self.latest_neighbour_sols[decoded_ilnp_dgram["src_id"]] = decoded_neigbour_sol["neighbour_sol_no"]

                # ignore neighbour solicitations not meant for this node
                if decoded_neigbour_sol["neighbour_id"] not in [self.BROADCAST_IDENTIFIER, self.device_id]:
                    return

                # forward solicitations if necessary
                if decoded_ilnp_dgram["dst_id"] == self.BROADCAST_IDENTIFIER and self.is_router:
                    self.forward_flood(decoded_link_frame["payload"], [decoded_link_frame["loc"]])

                # flood neighbour ad
                na = self.get_neighbour_ad()
                self.flood(na, NextHeader.CONTROL.value, [])


    def remove_outstanding_ack(self, responder):
        """
        Accept acknowledgement from responder for outstanding locator update
        """

        # if this acknowledgement is unexpected, ignore it
        if self.unacked_lu is None or responder not in self.unacked_lu.outstanding_acks:
            return

        # remove sender from outstanding acknowledgements list
        self.unacked_lu.outstanding_acks.remove(responder)

        # enact the locator update if this was the last remaining ack
        if len(self.unacked_lu.outstanding_acks) == 0:
            self.enact_unacked_lu()

    def resolve_timed_out_locs(self):
        """
        Leave locators that were timed out, but could not be left at the time due to another ongoing handoff
        """

        if len(self.timed_out_aged_locs) == 0:
            return

        # Leave the timed out locators
        for loc in self.timed_out_aged_locs:
            self.delete_loc_transport(loc)

        self.timed_out_aged_locs = set()

        self.loc_set_no += 1

        # flood neighbour ad
        na = self.get_neighbour_ad()
        self.flood(na, NextHeader.CONTROL.value, [])

    def process_lu(self, lu, is_router):
        """
        Process this locator update
        """

        decoded_lu = decode_locator_update(lu)

        # Ignore locator update if it is not from a correspondent
        if decoded_lu["id"] == self.device_id or decoded_lu["id"] not in self.correspondents:
            return

        # If this locator update does not build on the most recently seen locator set number, ignore it
        if self.loc_set_nos.get(decoded_lu["id"], -1) != decoded_lu["loc_set_no"] - 1:
            return

        now = time.time()

        # For soft adds, add active locator entries to the ilv cache
        if decoded_lu["action"] == LUAction.ILNP_LU_ADD_SOFT.value:
            for loc in decoded_lu["locs"]:
                self.ilv_cache[decoded_lu["id"]][loc] = RemoteLocEntry(LocatorFlag.ACTIVE.value,
                                                                       now + self.remote_loc_active_timeout, now)

                # add sender to entries in routers by loc if it is a router
                if is_router:
                    if loc not in self.routers_by_loc:
                        self.routers_by_loc[loc] = set()

                    self.routers_by_loc[loc].update([decoded_lu["id"]])

        # delete entries in ilv cache if it is a soft delete
        elif decoded_lu["action"] == LUAction.ILNP_LU_DELETE_SOFT.value:
            for loc in decoded_lu["locs"]:
                del self.ilv_cache[decoded_lu["id"]][loc]

                # ensure sender is not in current entry of routers by loc
                if decoded_lu["id"] in self.routers_by_loc.get(loc, {}):
                    self.routers_by_loc[loc].remove(decoded_lu["id"])

        # add and remove entries in ilv cache if locator update is a soft replace
        elif decoded_lu["action"] == LUAction.ILNP_LU_REPLACE_SOFT.value:

            # remove from routers by loc
            for loc in self.ilv_cache[decoded_lu["id"]]:
                if decoded_lu["id"] in self.routers_by_loc.get(loc, {}):
                    self.routers_by_loc[loc].remove(decoded_lu["id"])

            # clear senders entry in ilv cache
            self.ilv_cache[decoded_lu["id"]] = {}

            # add entries to ilv cache
            for loc in decoded_lu["locs"]:
                self.ilv_cache[decoded_lu["id"]][loc] = RemoteLocEntry(LocatorFlag.ACTIVE.value,
                                                                       now + self.remote_loc_active_timeout, now)
                # add to entries in routers by loc if sender is a router
                if is_router:
                    if loc not in self.routers_by_loc:
                        self.routers_by_loc[loc] = set()

                    self.routers_by_loc[loc].update([decoded_lu["id"]])

        # send acknowledgement 
        ack = get_lu_ack(lu)

        self.loc_set_nos[decoded_lu["id"]] = decoded_lu["loc_set_no"]

        self.send(decoded_lu["id"], ack, NextHeader.CONTROL.value)

    def enact_unacked_lu(self):
        """
        Enact the locator update which is awaiting acknowledgement
        """
        if self.unacked_lu is None:
            return

        now = time.time()

        locs = list(self.own_locs_cache)

        # loop through the node's own locators (ie not the broadcast locator and not the invariant ones)
        for loc in locs:

            # finish joining the locators that the locator update said would be joined
            if self.own_locs_cache[loc].flag == LocatorFlag.VALID_JOIN.value:

                
                if self.own_locs_cache[loc].timeout > now:
                    self.own_locs_cache[loc].flag = LocatorFlag.ACTIVE.value

                # if the locator has since timed out, set its flag to AGED
                else:

                    self.own_locs_cache[loc].flag = LocatorFlag.AGED.value
                    self.own_locs_cache[loc].timeout = now + self.own_loc_aged_timeout

            # finish leaving the locators that the locator update said would be left
            elif self.own_locs_cache[loc].flag == LocatorFlag.VALID_LEAVE.value:
                self.delete_loc_transport(loc)

        # update locator set number
        self.loc_set_no = self.unacked_lu.decoded_lu["loc_set_no"]
        self.unacked_lu = None
        self.has_unacked_lu.clear()

        # leave any locators that timed out while this handoff was being resolved
        self.resolve_timed_out_locs()

        # flood neighbour ad
        na = self.get_neighbour_ad()
        self.flood(na, NextHeader.CONTROL.value, [])

    def get_indexed_item(self, item_index):
        """
        Return object that the passed index refers to
        """
        if item_index == GetCommandIndex.FORWARDING_TABLE.value:
            return self.forwarding_table
        elif item_index == GetCommandIndex.ALL_LOCS.value:
            return list(set(self.loc_transports) - {self.BROADCAST_LOC})
        elif item_index == GetCommandIndex.INV_LOCS.value:
            return list(set(self.inv_locs))
        elif item_index == GetCommandIndex.CORRESPONDENTS.value:
            return list(self.correspondents)
        elif item_index == GetCommandIndex.ILV_CACHE.value:
            return self.ilv_cache
        elif item_index == GetCommandIndex.AVAILABLE_ROUTERS.value:
            return self.available_routers
        else:
            return None

    # Learned to use psutil here: https://psutil.readthedocs.io/en/latest/
    def get_indexed_value_bytes(self, value_index):
        """
        Return the bytes of the value the passed index refers to
        """
        if value_index == ValueIndex.ID.value:
            return int.to_bytes(self.device_id, VALUE_SIZES[value_index], "little", signed=True)
        elif value_index == ValueIndex.IS_ROUTER.value:
            return int.to_bytes(self.is_router, VALUE_SIZES[value_index], "little", signed=True)
        elif value_index == ValueIndex.CPU_TIME.value:
            return get_cpu_time(self.process)
        elif value_index == ValueIndex.RSS.value:
            return int.to_bytes(get_rss(self.process), VALUE_SIZES[value_index], "little", signed=True)
        elif value_index == ValueIndex.VIRTUAL_MEM.value:
            return int.to_bytes(get_virtual_mem(self.process), VALUE_SIZES[value_index], "little", signed=True)
        elif value_index == ValueIndex.OVERHEAD.value:
            return struct.pack("IIIIIIII", self.ilnp_dgrams_sent, self.ilnp_bytes_sent, self.app_dgrams_sent,
                               self.app_bytes_sent, self.ilnp_dgrams_recvd, self.ilnp_bytes_recvd,
                               self.app_dgrams_recvd, self.app_bytes_recvd)
        elif value_index == ValueIndex.RUNTIME.value:
            return struct.pack("d", time.time() - self.start_time)
        else:
            return None


async def run(no_inv_locs, net_protocol, **kwargs):
    """
    Call which starts the emulated IoT
    """
    asyncio.current_task().set_name(RUNNER)

    # get dictionary containing config parameters
    settings_dict = get_yaml_dict("config.yml")

    if not validate_settings_dict(settings_dict):
        raise ValueError("Settings file supplied does not contain necessary parameters.")

    # get emulated iot object
    emulated_iot_device = EmulatedIoT(no_inv_locs, net_protocol, **settings_dict)

    # start the emulated iot, passing in any writer stream that needs to be informed once the tasks have started
    if "writer" in kwargs:
        await emulated_iot_device.start_emulated_iot(writer=kwargs["writer"])

    else:
        await emulated_iot_device.start_emulated_iot()
