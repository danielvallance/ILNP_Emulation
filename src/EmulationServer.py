#!/usr/bin/env python3

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
from ipv4_control_utilities import *
import main
import socket
from constants import *
import argparse
import traceback
import logging

class EmulationServer:
    """
    Emulation Management Server
    """
    def __init__(self, port):
        self.port = port

        # Currently only one emulation allowed per device
        self.emulation_active = asyncio.Event()
        self.emulation_task = None



    # Runs the server
    async def start_emulation_server(self):
        asyncio.current_task().set_name(SERVER)
        handler = await asyncio.start_server(self.handle_emulation_reqs, socket.gethostbyname(socket.gethostname()),
                                             self.port)

        async with handler:
            await handler.serve_forever()

    # Function which handles API calls to the management server
    async def handle_emulation_reqs(self, reader, writer):

        asyncio.current_task().set_name(HANDLER)

        try:
            code_bytes = await reader.readexactly(1)
        except asyncio.exceptions.IncompleteReadError:
            return

        code = int.from_bytes(code_bytes, "little")

        if code == APICommandCode.START_IOT_DEVICE.value:

            if self.emulation_active.is_set():

                writer.write(int.to_bytes(-1, 1, "little", signed=True))
                await writer.drain()
                return

            cmd_bytes = bytes(code_bytes) + await reader.readexactly(cmd_sizes[code] - 1)

            decoded_cmd = decode_start_iot_device_command(cmd_bytes)


            self.emulation_active.set()

            print("About to run emulated IoT")

            try:
                self.emulation_task = asyncio.create_task(
                    main.run(decoded_cmd["no_inv_locs"], decoded_cmd["net_protocol"], writer=writer))

                await self.emulation_task

                print("stopped emulated IoT")
            except:
                traceback.print_exc()

            self.emulation_active.clear()



        elif code == APICommandCode.HANDSHAKE.value:

            if self.emulation_active.is_set():

                writer.write(int.to_bytes(-1, 1, "little", signed=True))
                await writer.drain()
                return

            writer.write(get_handshake_reply(not self.emulation_active.is_set()))
            await writer.drain()
            return
        elif code == APICommandCode.CANCEL.value:

            try:
                if self.emulation_active.is_set():
                    self.emulation_task.cancel()
                    await self.emulation_task
                    self.emulation_task = None
                    self.emulation_active.clear()
                writer.write(get_cancel_command())
                await writer.drain()
                return
            except:
                traceback.print_exc()

        else:
            writer.write(int.to_bytes(-1, 1, "little", signed=True))
            await writer.drain()
            return





if __name__ == "__main__":

    print("Running emulation management server")

    # Learned to use the argparse library for command line arguments here: https://docs.python.org/3/library/argparse.html
    parser = argparse.ArgumentParser()

    parser.add_argument("port", type=int)

    args = parser.parse_args()
    server = EmulationServer(args.port)

    asyncio.run(server.start_emulation_server())
