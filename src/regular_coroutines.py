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


import asyncio
import logging
from RemoteLocEntry import RemoteLocEntry
from OwnLocEntry import OwnLocEntry

from constants import *
from utilities import *

"""
This file contains coroutines that each emulated device regularly performs throughout its lifetime

These include:
    Distribution of advertisements
    Purging of soft state
    Resending locator updates
    
"""
async def flood_neighbour_ads(emulated_iot):

    while True:
        await asyncio.sleep(emulated_iot.neighbour_ad_interval)
        na = emulated_iot.get_neighbour_ad()

        # Flood the neighbour ad only if it is smaller than the maximum neighbour ad size
        if len(na) <= HeaderSizes["NEIGHBOUR_AD"] + emulated_iot.max_locs * 8:
            emulated_iot.flood(na, NextHeader.CONTROL.value, [])


async def broadcast_router_ads(emulated_iot):
    while True:
        await asyncio.sleep(emulated_iot.router_ad_interval)

        ra = emulated_iot.get_router_ad()

        # Broadcast the router ad only if it is smaller than the maximum router ad size
        if len(ra) <= HeaderSizes["ROUTER_AD"] + emulated_iot.max_locs * 8:
            emulated_iot.broadcast(ra, NextHeader.CONTROL.value)



async def purge_correspondents(emulated_iot):
    while True:
        await asyncio.sleep(emulated_iot.purge_rate_limit)
        now = time.time()
        next_timeout = None
        correspondents = {}

        for correspondent in emulated_iot.correspondents:
            timeout = emulated_iot.correspondents[correspondent]

            # If correspondent has not timed out add it to the new correspondents cache
            if now < timeout:
                correspondents[correspondent] = timeout

                if next_timeout is None or timeout < next_timeout:
                    next_timeout = timeout
            else:

                # If correspondent has timed out and the emulated IoT is awaiting an LU ACK from it, remove the requirement for this correspondent to send an ACK
                if emulated_iot.unacked_lu is not None and correspondent in emulated_iot.unacked_lu.outstanding_acks:
                    emulated_iot.remove_outstanding_ack(correspondent)

        # update correspondents cache
        emulated_iot.correspondents = correspondents

        if next_timeout is None:
            next_timeout = 0
        await asyncio.sleep(max(emulated_iot.purge_rate_limit, next_timeout - now))


async def purge_ilv_cache(emulated_iot):
    while True:

        await asyncio.sleep(emulated_iot.purge_rate_limit)
        now = time.time()
        next_timeout = None
        ilv_cache = {}

        for neighbour_id in emulated_iot.ilv_cache:
            ilv_cache[neighbour_id] = {}

            for loc in emulated_iot.ilv_cache[neighbour_id]:
                loc_entry = emulated_iot.ilv_cache[neighbour_id][loc]

                # If ILV has not timed out, add it to the new ILV cache
                if now < loc_entry.timeout:
                    ilv_cache[neighbour_id][loc] = loc_entry
                    if next_timeout is None or loc_entry.timeout < next_timeout:
                        next_timeout = loc_entry.timeout
                else:

                    # Otherwise either update its flag, or do not add it
                    if loc_entry.flag == LocatorFlag.ACTIVE.value:
                        if now - loc_entry.last_used < emulated_iot.last_used_timeout:
                            ilv_cache[neighbour_id][loc] = RemoteLocEntry(LocatorFlag.EXPIRED.value,
                                                                          now + emulated_iot.remote_loc_expired_timeout,
                                                                          loc_entry.last_used)
                        else:
                            ilv_cache[neighbour_id][loc] = RemoteLocEntry(LocatorFlag.AGED.value,
                                                                          now + emulated_iot.remote_loc_aged_timeout,
                                                                          loc_entry.last_used)

                            if neighbour_id in emulated_iot.routers_by_loc.get(loc, set()):
                                emulated_iot.routers_by_loc[loc].remove(neighbour_id)



                        if next_timeout is None or ilv_cache[neighbour_id][loc].timeout < next_timeout:
                            next_timeout = ilv_cache[neighbour_id][loc].timeout
                    elif loc_entry.flag == LocatorFlag.EXPIRED.value:
                        if neighbour_id in emulated_iot.routers_by_loc.get(loc, set()):
                            emulated_iot.routers_by_loc[loc].remove(neighbour_id)

            if len(ilv_cache[neighbour_id]) == 0:
                del ilv_cache[neighbour_id]




        emulated_iot.ilv_cache = ilv_cache

        if next_timeout is None:
            next_timeout = 0

        await asyncio.sleep(max(emulated_iot.purge_rate_limit, next_timeout - now))


async def purge_own_locs(emulated_iot):

    while True:
        await asyncio.sleep(emulated_iot.purge_rate_limit)
        now = time.time()
        next_timeout = None
        own_locs_cache = {}
        to_leave = []

        for loc in emulated_iot.own_locs_cache:
            entry = emulated_iot.own_locs_cache[loc]

            # If locator has no timeout or it has not timed out add it to new own locs cache
            if entry.timeout is None:
                own_locs_cache[loc] = emulated_iot.own_locs_cache[loc]
            elif now < entry.timeout:
                if next_timeout is None or entry.timeout < next_timeout:
                    next_timeout = entry.timeout
                own_locs_cache[loc] = emulated_iot.own_locs_cache[loc]
            else:

                # Otherwise add a version with its flag updated or do not add it
                if entry.flag == LocatorFlag.ACTIVE.value:

                    own_locs_cache[loc] = OwnLocEntry(LocatorFlag.AGED.value, now + emulated_iot.own_loc_aged_timeout)
                    if next_timeout is None or own_locs_cache[loc].timeout < next_timeout:
                        next_timeout = own_locs_cache[loc].timeout

                elif entry.flag == LocatorFlag.AGED.value:
                    to_leave.append(loc)

                elif entry.flag in [LocatorFlag.VALID_JOIN.value, LocatorFlag.VALID_LEAVE.value]:
                    own_locs_cache[loc] = emulated_iot.own_locs_cache[loc]

        # Attempt to leave all timed out locs - if there is a handoff currently happening this must wait
        if len(to_leave) > 0:
            emulated_iot.timed_out_aged_locs.update(to_leave)
            if not emulated_iot.handing_off.is_set():
                emulated_iot.resolve_timed_out_locs()

        emulated_iot.own_locs_cache = own_locs_cache

        if next_timeout is None:
            next_timeout = 0

        await asyncio.sleep(max(emulated_iot.purge_rate_limit, next_timeout - now))


async def purge_available_routers(emulated_iot):
    while True:
        await asyncio.sleep(emulated_iot.purge_rate_limit)
        now = time.time()
        next_timeout = None
        available_routers = {}


        for router_id in emulated_iot.available_routers:
            timeout = emulated_iot.available_routers[router_id].timeout

            # If router has not timed out add it to the new available routers cache
            if now < timeout:
                available_routers[router_id] = emulated_iot.available_routers[router_id]

                if next_timeout is None or timeout < next_timeout:
                    next_timeout = timeout


        emulated_iot.available_routers = available_routers

        if next_timeout is None:
            next_timeout = 0

        await asyncio.sleep(max(emulated_iot.purge_rate_limit, next_timeout - now))


async def purge_forwarding_table(emulated_iot):
    while True:
        await asyncio.sleep(emulated_iot.purge_rate_limit)
        now = time.time()
        next_timeout = None
        forwarding_table = {}

        for loc in emulated_iot.forwarding_table:
            forwarding_table[loc] = []
            for fwd_entry in emulated_iot.forwarding_table[loc]:

                # If forwarding entry has not timed out add it to the new forwarding table
                if now < fwd_entry.timeout:
                    forwarding_table[loc].append(fwd_entry)

                    if next_timeout is None or fwd_entry.timeout < next_timeout:
                        next_timeout = fwd_entry.timeout

            if len(forwarding_table[loc]) == 0:
                del forwarding_table[loc]

        emulated_iot.forwarding_table = forwarding_table

        if next_timeout is None:
            next_timeout = 0

        await asyncio.sleep(max(emulated_iot.purge_rate_limit, next_timeout - now))


async def process_unacked_lu(emulated_iot):
    while True:

        # Wait until there is an unacked LU
        await emulated_iot.has_unacked_lu.wait()
        if emulated_iot.unacked_lu.resends < 4:
            await asyncio.sleep(emulated_iot.lu_resend_interval)

            # Resend LU to correspondents that have not acknowledged the locator update
            for correspondent in emulated_iot.unacked_lu.outstanding_acks:
                emulated_iot.send(correspondent, emulated_iot.unacked_lu.lu, NextHeader.CONTROL.value)
                emulated_iot.unacked_lu.resends += 1

            # After 4 retransmissions just enact the LU
            else:
                emulated_iot.enact_unacked_lu()
