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


import sys
import argparse
import traceback
import asyncio
import random
import math
import time

sys.path.append("../../../")
sys.path.append("../")
from emulation_api import *
from emergency_comms_utilities import *
from utilities import *
from ReceivedAppData import ReceivedAppData
from BaseIoT import BaseIoT

class Mobile(BaseIoT):
    """
    Object representing mobile in the emergency communication network scenario
    """
    def __init__(self, iot, app_port, role):
        BaseIoT.__init__(self, iot, app_port)

        self.role = role
        self.seq_no = 0

        self.sending_task = None
        self.process_flow_task = None
        self.mobility_task = None

        self.send_reader = None
        self.send_writer = None
        self.recv_reader = None
        self.recv_writer = None

        self.delays = {}


    async def initialise_streams(self):
        """
        Set up asyncio streams to make API calls
        """

        await super().initialise_management_streams()

        await super().initialise_res_streams()

        self.mobility_reader, self.mobility_writer = await self.iot_device.get_iot_device_conn()
        if self.role == Roles.SENDER.value:
            self.send_reader, self.send_writer = await self.iot_device.get_iot_device_conn()

        if self.role == Roles.RECEIVER.value:
            self.recv_reader, self.recv_writer = await self.iot_device.get_iot_device_conn()




    async def start_mobile(self, res_interval, locs, mobility_interval, **kwargs):
        """
        Start asyncio tasks the Mobile performs
        """
        self.running = True

        self.socket = await self.iot_device.create_socket(self.app_port, self.management_reader, self.management_writer)

        self.res_task = asyncio.create_task(self.record_resources(res_interval))

        self.mobility_task = asyncio.create_task(self.move(locs, mobility_interval))

        if self.role == Roles.RECEIVER.value:
            self.process_flow_task = asyncio.create_task(self.process_flow())

        if self.role == Roles.SENDER.value:
            self.sending_task = asyncio.create_task(
                self.send_flow(kwargs["rate"], kwargs["receiver_id"], kwargs["dgrams_to_send"]))

            return self.sending_task


    async def close_mobile(self):
        """
        Stop asyncio tasks that mobile performs
        """

        self.running = False

        if self.sending_task is not None:
            await self.sending_task

        if self.process_flow_task is not None:
            self.process_flow_task.cancel()
            await self.process_flow_task


        if self.mobility_task is not None:
            self.mobility_task.cancel()
            await self.mobility_task

        await self.cancel_resources_task()

        await self.socket.close(self.management_reader, self.management_writer)

        await self.iot_device.quit(self.management_reader, self.management_writer)

        if self.send_writer is not None:
            self.send_writer.close()

        if self.recv_writer is not None:
            self.recv_writer.close()

        self.mobility_writer.close()

        self.close_streams()

        del self



    async def process_flow(self):
        """
        Record data on delay and delivery as application packets come in
        """
        try:
            while self.running:

                recv_details = await self.socket.recv(self.recv_reader, self.recv_writer)

                decoded_flow_packet = decode_flow_packet(recv_details.payload)


                self.delays[decoded_flow_packet["seq_no"]] = math.floor(time.time_ns()/1000000) - decoded_flow_packet["timestamp"]


        except asyncio.CancelledError:
            return


    async def move(self, locs, interval):
        """
        Randomly replace locator set of underlying emulated IoT
        """

        if not locs:
            return

        try:


            while self.running:

                await asyncio.sleep(interval)

                

                next_locs = random.choices(list(locs),k=2)

                next_locs = list(set(next_locs))


                ret = await self.iot_device.replace(self.mobility_reader, self.mobility_writer, *next_locs)



                print(ret)




        except asyncio.CancelledError:

            return

    async def send_flow(self, rate, dst_id, dgrams_to_send):
        """
        Send application packet flow
        """

        while self.running:
            # stop once the flow is completed
            if self.seq_no >= dgrams_to_send:
                return

            await self.socket.send(dst_id, self.app_port, get_flow_packet(self.seq_no), self.send_reader,
                                   self.send_writer)
            self.seq_no += 1

            await asyncio.sleep(1 / rate)

