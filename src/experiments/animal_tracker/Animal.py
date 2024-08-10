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

from animal_tracker_utilities import *
from animal_tracker_constants import *
import traceback
import random
import sys

sys.path.append("../")
from BaseIoT import BaseIoT

class Animal(BaseIoT):
    """
    Object representing animal IoT
    """

    def __init__(self, iot, app_port):
        BaseIoT.__init__(self, iot, app_port)

        self.process_queries_task = None
        self.mobility_task = None

        self.query_reader = None
        self.query_writer = None
        self.mobility_reader = None
        self.mobility_writer = None




    async def process_queries(self):
        """
        Responds to location queries
        """
        try:
            while self.running:

                recv_details = await self.socket.recv(self.query_reader, self.query_writer)

                if recv_details.payload[0] != REQUEST:
                    continue

                print("Received request")

                decoded_tracking_request_dgram = decode_tracking_request_dgram(recv_details.payload)

                print(decoded_tracking_request_dgram)

                tracking_response_dgram = get_tracking_response_dgram(decoded_tracking_request_dgram["req_no"], recv_details.prev_hop_loc)

                await self.socket.send(recv_details.src_id, self.app_port, tracking_response_dgram, self.query_reader, self.query_writer)

        except asyncio.CancelledError:
            return

    async def initialise_streams(self):
        """
        Set up asyncio streams used to make API calls
        """
        await super().initialise_management_streams()

        await super().initialise_res_streams()
        self.query_reader, self.query_writer = await self.iot_device.get_iot_device_conn()
        self.mobility_reader, self.mobility_writer = await self.iot_device.get_iot_device_conn()


    async def start_animal(self, locators, mobility_interval, res_interval):
        """
        Start asyncio tasks this object performs
        """

        self.running = True
        self.socket = await self.iot_device.create_socket(self.app_port, self.management_reader, self.management_writer)
        self.res_task = asyncio.create_task(self.record_resources(res_interval))


        self.process_queries_task = asyncio.create_task(self.process_queries())
        self.mobility_task = asyncio.create_task(self.move(locators, mobility_interval))


    async def close_animal(self):
        """
        Stop asyncio tasks this object performs
        """
        self.running = False

        if self.process_queries_task is not None:
            self.process_queries_task.cancel()
            await self.process_queries_task

        if self.mobility_task is not None:
            self.mobility_task.cancel()
            await self.mobility_task

        await self.cancel_resources_task()

        await self.socket.close(self.management_reader, self.management_writer)

        await self.iot_device.quit(self.management_reader, self.management_writer)

        self.query_writer.close()
        self.mobility_writer.close()

        self.close_streams()
        del self




    async def move(self, locators,  interval):
        """
        Randomly changes connectivity every interval simulating movement
        """

        current_loc = 0

        try:

            while self.running:

                await asyncio.sleep(interval)

                next_locs = [loc for loc in locators if loc != current_loc]

                next_loc = random.choices(next_locs)[0]

                print("Moving to " + str(next_loc))


                ret = await self.iot_device.replace(self.mobility_reader, self.mobility_writer, next_loc)

                current_loc = next_loc


        except asyncio.CancelledError:

            return
