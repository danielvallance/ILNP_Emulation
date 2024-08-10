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


import logging
import asyncio
import pickle
from queue import Queue
import traceback

from constants import *
from ipv4_control_utilities import *
from utilities import *


"""
This file contains the logic that the emulated IoT uses to service API calls
"""

async def api_server(emulated_iot):
    # Learned about async streams here and how to start an asyncio server here:
    # https://docs.python.org/3/library/asyncio-stream.html
    # https://superfastpython.com/python-asyncio/
    # https://stackoverflow.com/questions/48506460/python-simple-socket-client-server-using-asyncio

    handler = await asyncio.start_server(lambda reader, writer: process_mgmt_cmds(reader, writer, emulated_iot),
                                         socket.gethostbyname(socket.gethostname()), emulated_iot.mgmt_port)

    async with handler:
        emulated_iot.api_server_active.set()
        await handler.serve_forever()


async def process_mgmt_cmds(reader, writer, emulated_iot):

    try:
        while True:

            # Get the type field and check it is valid
            code_bytes = await reader.readexactly(1)

            code = int.from_bytes(code_bytes, "little")

            if code not in cmd_sizes:
                return


            # get rest of command and decode it
            command_bytes = code_bytes + await reader.readexactly(cmd_sizes[code] - 1)
            decoded_command = type_to_decoder[code](command_bytes)

            # Create socket
            if decoded_command["code"] == APICommandCode.CREATE_SOCK.value:

                # Fail if socket already on port
                if decoded_command["port"] in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 1, "little", signed=True))
                    await writer.drain()
                    return

                # Create queue representing socket, and event representing that there is data available
                emulated_iot.port_qs[decoded_command["port"]] = Queue()
                emulated_iot.port_events[decoded_command["port"]] = asyncio.Event()

                writer.write(int.to_bytes(0, 1, "little", signed=True))
                await writer.drain()

            # Close the socket
            elif decoded_command["code"] == APICommandCode.CLOSE_SOCK.value:
                if decoded_command["port"] not in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 1, "little", signed=True))
                    await writer.drain()
                    return

                del emulated_iot.port_qs[decoded_command["port"]]
                del emulated_iot.port_events[decoded_command["port"]]

                writer.write(int.to_bytes(0, 1, "little", signed=True))
                await writer.drain()

            # Receive data from socket
            elif decoded_command["code"] == APICommandCode.RECV.value:

                # Fail if port does not exist
                if decoded_command["port"] not in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 8, "little", signed=True))
                    await writer.drain()
                    return

                # Wait for data to become available then return it
                await emulated_iot.port_events[decoded_command["port"]].wait()

                payload = emulated_iot.port_qs[decoded_command["port"]].get()

                if emulated_iot.port_qs[decoded_command["port"]].empty():
                    emulated_iot.port_events[decoded_command["port"]].clear()

                writer.write(int.to_bytes(len(payload), 8, "little", signed=True))
                writer.write(payload)
                await writer.drain()

            # Check if socket has data
            elif decoded_command["code"] == APICommandCode.HAS_DATA.value:

                # Fail if port does not exist
                if decoded_command["port"] not in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 1, "little", signed=True))
                    await writer.drain()
                    return

                # Return whether the port has data
                if emulated_iot.port_events[decoded_command["port"]].empty():
                    ret = 0
                else:
                    ret = 1

                writer.write(ret, 1, "little", signed=True)
                await writer.drain()


            # Send data
            elif decoded_command["code"] == APICommandCode.SEND.value:

                if decoded_command["src_port"] not in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 1, "little", signed=True))
                    await writer.drain()
                    return

                # Get payload being sent
                payload = await reader.readexactly(decoded_command["data_length"])

                # Get transport dgrams
                transport_dgrams = emulated_iot.get_transport_dgram(decoded_command["src_port"], decoded_command["dst_port"], payload, False)

                # Send the transport dgrams
                ret = 0
                for transport_dgram in transport_dgrams:
                    if not emulated_iot.send(decoded_command["id"], transport_dgram, NextHeader.TRANSPORT.value):
                        ret = -1
                        break


                writer.write(int.to_bytes(ret, 1, "little", signed=True))
                await writer.drain()

            # Join locator set
            elif decoded_command["code"] == APICommandCode.JOIN.value:

                # Get locator set
                locs = [int.from_bytes(await reader.readexactly(8), "little") for i in range(decoded_command["no_of_locs"])]

                # Attempt to join and return whether it was successful
                if await emulated_iot.join(locs):
                    ret = 0
                else:
                    ret = -1
                writer.write(int.to_bytes(ret, 1, "little", signed=True))

                await writer.drain()

            # Attempt to leave a locator set
            elif decoded_command["code"] == APICommandCode.LEAVE.value:

                # Get the locator set
                locs = [int.from_bytes(await reader.readexactly(8), "little") for i in range(decoded_command["no_of_locs"])]

                # Attempt to leave the locator set and return whether it was successful
                if emulated_iot.leave(locs):
                    ret = 0
                else:
                    ret = -1

                writer.write(int.to_bytes(ret, 1, "little", signed=True))
                await writer.drain()

            # Return value being getted
            elif decoded_command["code"] == APICommandCode.GET_VALUE.value:
                value_bytes = emulated_iot.get_indexed_value_bytes(decoded_command["value_index"])
                writer.write(value_bytes)
                await writer.drain()

            # Flood data
            elif decoded_command["code"] == APICommandCode.FLOOD.value:



                if decoded_command["src_port"] not in emulated_iot.port_qs:
                    writer.write(int.to_bytes(-1, 1, "little", signed=True))
                    await writer.drain()
                    return

                # Get payload
                payload = await reader.readexactly(decoded_command["data_length"])

                # Get transport dgrams
                transport_dgrams = emulated_iot.get_transport_dgram(decoded_command["src_port"], decoded_command["dst_port"], payload, True)

                # Flood each transport dgram
                ret = 0
                for transport_dgram in transport_dgrams:
                    if not emulated_iot.flood(transport_dgram, NextHeader.TRANSPORT.value, []):
                        ret = -1
                        break


                writer.write(int.to_bytes(ret, 1, "little", signed=True))
                await writer.drain()

            # Stop the emulated IoT
            elif decoded_command["code"] == APICommandCode.QUIT.value:
                await emulated_iot.stop_emulated_iot(writer=writer)

            # Replace the locator set
            elif decoded_command["code"] == APICommandCode.REPLACE.value:

                # Get the locator set
                locs = [int.from_bytes(await reader.readexactly(8), "little") for i in range(decoded_command["no_of_locs"])]

                # Attempt to replace locator set and return whether it was successful
                if await emulated_iot.replace(locs):
                    ret = 0
                else:
                    ret = 1
                writer.write(int.to_bytes(ret, 1, "little", signed=True))
                await writer.drain()

            # Get an object in the emulated IoT's state
            elif decoded_command["code"] == APICommandCode.GET.value:

                requested_obj = emulated_iot.get_indexed_item(decoded_command["item_index"])

                if requested_obj is None:
                    writer.write(int.to_bytes(-1, 8, "little", signed=True))

                # Serialise the object and send it
                pickled_obj = pickle.dumps(requested_obj)

                writer.write(int.to_bytes(len(pickled_obj), 8, "little", signed=True))

                writer.write(pickled_obj)
                await writer.drain()

    except asyncio.exceptions.IncompleteReadError as e:
        return