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


import pickle
from ipv4_control_utilities import *
from utilities import *
from ReceivedAppData import ReceivedAppData
import asyncio
import sys
import traceback
from get_yaml_dict import get_yaml_dict

async def create_topology(config_file, net_protocol):
    """
    Creates a network of emulated IoT devices with the topology specified in the topology file referred to in the passed config file

    The emulated IoTs will run over the passed net_protocol too
    """
    hosts = []
    locators = {}
    iots = {}

    settings_dict = get_yaml_dict(config_file)


    with open(settings_dict["hosts_file"]) as opened_hosts_file:
        for line in opened_hosts_file:
            hosts.append(line.strip())

    topology = get_yaml_dict(settings_dict["topology_file"])["topology"]


    for iot_name in topology:
        if "inv" in topology[iot_name]:
            invariant_locs = len(topology[iot_name]["inv"])
        else:
            invariant_locs = -1
        iot, hosts = await get_running_iot(hosts, settings_dict, invariant_locs, net_protocol)

        if not iot:
            await close_iots(iots)
            raise ValueError("Could not create topology")

        iots[iot_name] = iot

        r, w = await iot.get_iot_device_conn()

        res = await iot.join(r, w, *[locators[join_index] for join_index in
                                                     topology[iot_name]["joined"]])

        if not res:
            await close_iots(iots)
            raise ValueError("Could not create toplogy")

        locs = await iot.get_locs(r,w)
        print(locs)

        if "inv" in topology[iot_name]:
            for index in topology[iot_name]["inv"]:
                locators[index] = locs.pop(0)

        w.close()
        print("completed setting up: " + iot_name)

    return iots

async def close_iots(iots):
    """
    Closes the iots which were created in the create topology call if a later attempt to start another emulated IoT failed
    """
    for iot in iots:
        r,w = await iots[iot].get_iot_device_conn()

        await iots[iot].quit(r, w)

async def check_servers(hostsfilename, port, timeout):
    """
    Returns which hosts are available to host an emulated IoT and which are not, out of the hosts listed in the passed hosts file
    """
    available = []
    unavailable = []

    with open(hostsfilename) as hostsfile:
        for host in hostsfile:
            if await handshake(host, port, timeout):
                available.append(host)

            else:
                unavailable.append(host)

    return available, unavailable


async def get_running_iot(hosts, settings_dict, no_of_locs, net_protocol):

    """
    Start an emulated IoT device on one of the hosts in the passed hosts file, which runs over the network protocol specified, 
    and has the number of invariant locators passed (-1 should be passed if the node is not going to take part in forwarding).
    
    The settings_dict passed will determine the port it will use to check for emulation servers, the handshake timeout and the port 
    that the emulated IoT's will service API requests on
    """

    hosts_copy = [host for host in hosts]

    # learned about wait for here: https://superfastpython.com/asyncio-wait_for/#What_is_Asyncio_wait_for

    iot = False
    for host in hosts_copy:
        try:
            print("Starting handshake with: " + host)
            if not await handshake(host, settings_dict["server_port"],
                                          settings_dict["handshake_timeout"]):
                print("Handshake refused from: " + host)
                hosts.remove(host)
                continue
            print("Handshake accepted")
            iot = await get_iot_device(host, settings_dict["server_port"], settings_dict["emulation_port"], no_of_locs,
                                       net_protocol)

            hosts.remove(host)
            if iot:
                print("Created emulated iot device at: " + host)
                break
            else:
                print("Could not create emulated iot device at: " + host)

        except:
            print("Connection refused from: " + host)
            hosts.remove(host)
            continue

    return iot, hosts


async def cancel(hostname, server_port):

    """
    Cancels the task running an emulated IoT
    """
    try:
        r,w = await asyncio.open_connection(hostname, server_port)

        w.write(get_cancel_command())
        await w.drain()

        code_bytes = await r.readexactly(1)

        code = int.from_bytes(code_bytes, "little")


        if code != APICommandCode.CANCEL.value:

            return False

        else:
            w.close()
            return True
    except:

        return False


async def handshake(hostname, server_port, timeout):
    """
    Handshakes with the emulation management server to determine whether it is available to run an emulated IoT
    """
    try:

        # Learned about the wait_for function to set a timeout on awaiting an event here: https://superfastpython.com/asyncio-wait_for/#What_is_Asyncio_wait_for
        r,w = await asyncio.wait_for(asyncio.open_connection(hostname, server_port), timeout)
        w.write(get_handshake_command())
        await w.drain()

        code_bytes = await r.readexactly(1)

        code = int.from_bytes(code_bytes, "little")

        if code != APICommandCode.HANDSHAKE_REPLY.value:
            return False

        command_bytes = code_bytes + await r.readexactly(cmd_sizes[code] - 1)



        decoded_handshake_reply = type_to_decoder[code](command_bytes)

        w.close()


        return decoded_handshake_reply["available"]

    except:

        return False





async def get_iot_device(hostname, server_port, emulation_port, no_inv_locs, net_protocol):
    """
    Sends request to emulation server on (hostname, server_port) to start an instance of the emulated device which uses the specified 
    net_protocol and has the specified number of invariant locators (-1 should be passed if the node should not take part in forwarding)

    The emulation_port argument specifies the port which the emulated IoT device will service API calls on
    """

    r, w = await asyncio.open_connection(hostname, server_port)

    cmd = get_start_iot_device_command(no_inv_locs, net_protocol)

    w.write(cmd)
    await w.drain()



    ret = int.from_bytes(await r.readexactly(1), "little", signed=True)

    if ret == -1:
        w.close()
        return False

    w.close()


    return IoTDevice(hostname, emulation_port, net_protocol)


class IoTDevice:

    """
    Class representing emulated IoT device
    """

    def __init__(self, hostname, port, net_protocol):
        """
        Constructor
        """
        self.sockets = {}
        self.hostname = hostname
        self.port = port
        self.registered_readers = set()
        self.registered_writers = set()
        self.rw_locks = {}
        self.net_protocol = net_protocol

    async def get_iot_device_conn(self):
        """
        Gets streams which are connected to the IoTDevice which are required to make API calls over the network
        """

        # learned to open tcp connection with asyncio here: https://superfastpython.com/python-asyncio/
        r, w = await asyncio.open_connection(self.hostname, self.port)
        self.registered_readers.add(r)
        self.registered_writers.add(w)
        self.rw_locks[(r, w)] = asyncio.Lock()
        return r, w

    async def create_socket(self, port, reader, writer):

        """
        Creates a socket for the emulated IoT on the given port and returns it
        """

        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:

            if port in self.sockets:
                return False

            cmd = get_create_sock_cmd(port)
            writer.write(cmd)
            await writer.drain()

            ret = int.from_bytes(await reader.readexactly(1), "little", signed=True)
            if ret == -1:
                return False

            self.sockets[port] = IotSocket(self, port)

            return self.sockets[port]

    async def join(self, reader, writer, *args):

        """
        Attempts to add the passed in locators to the emulated IoT's locator set
        """

        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:
            cmd = get_join_command(args)
            writer.write(cmd)
            await writer.drain()

            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 0

    async def leave(self, reader, writer, *args):

        """
        Attempts to remove the given locators from the emulated IoT's locator set
        """

        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:
            cmd = get_leave_command(args)
            writer.write(cmd)
            await writer.drain()

            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 0

    async def replace(self, reader, writer, *args):

        """
        Attempts to replace the emulated IoT's locator set
        """

        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:
            cmd = get_replace_command(args)
            writer.write(cmd)
            await writer.drain()

            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 0

    async def is_router(self, reader, writer):
        """
        Returns a boolean representing whether the emulated IoT device performs routing/forwarding
        """

        is_router_bytes = await self.get_value_command(ValueIndex.IS_ROUTER.value, reader, writer)

        return bool.from_bytes(is_router_bytes, "little", signed=True)

    async def get_id(self, reader, writer):

        """
        Get the identifer of the emulated IoT device
        """

        id_bytes = await self.get_value_command(ValueIndex.ID.value, reader, writer)
        return int.from_bytes(id_bytes, "little", signed=True)

    async def get_overhead(self, reader, writer):
        """
        Get the overhead statistics of the emulated IoT device
        """
        overhead_bytes = await self.get_value_command(ValueIndex.OVERHEAD.value, reader, writer)
        overhead = {}
        overhead["ilnp_dgrams_sent"] = int.from_bytes(overhead_bytes[0:4], "little")
        overhead["ilnp_bytes_sent"] = int.from_bytes(overhead_bytes[4:8], "little")
        overhead["app_dgrams_sent"] = int.from_bytes(overhead_bytes[8:12], "little")
        overhead["app_bytes_sent"] = int.from_bytes(overhead_bytes[12:16], "little")
        overhead["ilnp_dgrams_recvd"] = int.from_bytes(overhead_bytes[16:20], "little")
        overhead["ilnp_bytes_recvd"] = int.from_bytes(overhead_bytes[20:24], "little")
        overhead["app_dgrams_recvd"] = int.from_bytes(overhead_bytes[24:28], "little")
        overhead["app_bytes_recvd"] = int.from_bytes(overhead_bytes[28:32], "little")
        return overhead

    async def get_runtime(self, reader, writer):
        """
        Get the length of time this emulated IoT device has been running
        """
        runtime_bytes = await self.get_value_command(ValueIndex.RUNTIME.value, reader, writer)
        return struct.unpack("d", runtime_bytes)[0]

    async def get_cpu_time(self, reader, writer):
        """
        Get the CPU time of the process running the emualted IoT device
        """
        cpu_time_bytes = await self.get_value_command(ValueIndex.CPU_TIME.value, reader, writer)
        return struct.unpack("d", cpu_time_bytes)[0]

    async def get_virtual_mem(self, reader, writer):
        """
        Get the current size of the virtual memory of the process running the emulated IoT device
        """
        virtual_mem_bytes = await self.get_value_command(ValueIndex.VIRTUAL_MEM.value, reader, writer)
        return int.from_bytes(virtual_mem_bytes, "little", signed=True)

    async def get_rss(self, reader, writer):
        """
        Get the current RSS of the process running the emulated IoT device
        """
        rss_bytes = await self.get_value_command(ValueIndex.RSS.value, reader, writer)
        return int.from_bytes(rss_bytes, "little", signed=True)

    async def get_command(self, item_index, reader, writer):
        """
        Private method which enables generalised get command
        """
        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:

            cmd = get_get_command(item_index)
            writer.write(cmd)
            await writer.drain()

            size = int.from_bytes(await reader.readexactly(8), "little", signed=True)
            if size == -1:
                return False

            pickled_obj = await reader.readexactly(size)
            return pickle.loads(pickled_obj)

    async def get_value_command(self, value_index, reader, writer):
        """
        Private method which enables generalised get commands
        """
        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:
            cmd = get_get_value_command(value_index)
            writer.write(cmd)
            await writer.drain()

            return await reader.readexactly(VALUE_SIZES[value_index])

    async def get_ilv_cache(self, reader, writer):
        """
        Get the current state of this emulated IoT's ILV cache
        """
        return await self.get_command(GetCommandIndex.ILV_CACHE.value, reader, writer)

    async def get_forwarding_table(self, reader, writer):
        """
        Get the current state of this emulated IoT's forwarding table
        """
        return await self.get_command(GetCommandIndex.FORWARDING_TABLE.value, reader, writer)

    async def get_correspondents(self, reader, writer):
        """
        Get the emulated IoTs that have recently engaged in unicast communication with this emulated IoT device
        """
        return await self.get_command(GetCommandIndex.CORRESPONDENTS.value, reader, writer)

    async def get_available_routers(self, reader, writer):
        """
        Get which routers have recently sent a router advertisement to this emulated IoT device
        """
        return await self.get_command(GetCommandIndex.AVAILABLE_ROUTERS.value, reader, writer)

    async def get_locs(self, reader, writer):
        """
        Get all locators of the given emulated IoT device
        """
        return await self.get_command(GetCommandIndex.ALL_LOCS.value, reader, writer)

    async def get_inv_locs(self, reader, writer):
        """
        Get the invariant locators of the given emulated IoT device
        """
        return await self.get_command(GetCommandIndex.INV_LOCS.value, reader, writer)

    async def quit(self, reader, writer):

        """
        End this emulated IoT device and make the hosting machine return to running the emulation management server
        """

        if reader not in self.registered_readers or writer not in self.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.rw_locks[(reader, writer)]:

            cmd = get_quit_command()
            writer.write(cmd)
            await writer.drain()

            ret = int.from_bytes(await reader.readexactly(1), "little", signed=True)

            if ret == -1:

                for w in self.registered_writers:
                    w.close()
                del self
                return False

            else:
                for w in self.registered_writers:
                    w.close()
                del self
                return True






class IotSocket:
    """
    Transport layer socket of an emulated IoT device
    """
    def __init__(self, iot_device, port):
        """
        Socket constructor
        """
        self.iot_device = iot_device
        self.port = port

    async def flood(self, dst_port, data, reader, writer):

        """
        Flood the passed data throughout the network, on the passed port
        """

        if reader not in self.iot_device.registered_readers or writer not in self.iot_device.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.iot_device.rw_locks[(reader, writer)]:
            cmd = get_flood_command(self.port, dst_port, data)
            writer.write(cmd)
            await writer.drain()
            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 0


    async def send(self, dst_id, dst_port, data, reader, writer):

        """
        Sends the given data to the node with the given identifier, on the given port
        """

        if reader not in self.iot_device.registered_readers or writer not in self.iot_device.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.iot_device.rw_locks[(reader, writer)]:
            cmd = get_send_command(dst_id, self.port, dst_port, data)
            writer.write(cmd)
            await writer.drain()

            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 0

    async def recv(self, reader, writer):


        """
        Returns the oldest packet of data that has been sent to it that has not yet been returned
        """

        if reader not in self.iot_device.registered_readers or writer not in self.iot_device.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.iot_device.rw_locks[(reader, writer)]:

            cmd = get_recv_command(self.port)
            writer.write(cmd)
            await writer.drain()

            size = int.from_bytes(await reader.readexactly(8), "little", signed=True)

            if size == -1:
                return False

            link_frame = await reader.readexactly(size)

            decoded_link_frame = decode_link_frame(link_frame)
            decoded_ilnp_dgram = decode_ilnp_dgram(decoded_link_frame["payload"])
            decoded_transport_dgram = decode_transport_dgram(decoded_ilnp_dgram["payload"])
            payload = decoded_transport_dgram["payload"]

            ret = ReceivedAppData(decoded_link_frame["src_id"], decoded_link_frame["loc"],
                                  decoded_ilnp_dgram["src_id"],
                                  decoded_ilnp_dgram["src_loc"], decoded_transport_dgram["src_port"], payload)

            return ret

    async def close(self, reader, writer):

        """
        Closes the socket
        """


        if reader not in self.iot_device.registered_readers or writer not in self.iot_device.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.iot_device.rw_locks[(reader, writer)]:

            cmd = get_close_sock_cmd(self.port)
            writer.write(cmd)

            await writer.drain()

            ret = int.from_bytes(await reader.readexactly(1), "little", signed=True)
            if ret == -1:
                return False

            del self.iot_device.sockets[self.port]
            del self

            return True


    async def has_data(self, reader, writer):

        """
        Returns whether the given socket has any more data which can be returned by a call to recv.
        """

        if reader not in self.iot_device.registered_readers or writer not in self.iot_device.registered_writers:
            raise ValueError("Wrong reader or writer used")

        async with self.iot_device.rw_locks[(reader, writer)]:

            cmd = get_has_data_command(self.port)

            writer.write(cmd)
            await writer.drain()


            return int.from_bytes(await reader.readexactly(1), "little", signed=True) == 1
