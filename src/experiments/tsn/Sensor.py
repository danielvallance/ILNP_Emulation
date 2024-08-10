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


import random
import sys
import argparse
import time
import asyncio
import traceback
from Gradient import Gradient

import sys

sys.path.append("../../src")
sys.path.append("..")
from emulation_api import *
from tsn_utilities import *
from BaseIoT import BaseIoT

class Sensor(BaseIoT):
    """
    Class representing sensor in temperature sensor network
    """
    def __init__(self, iot, sink_id, app_port, paradigm):
        BaseIoT.__init__(self, iot, app_port)
        self.sink_id = sink_id
        self.seq_no = 0

        # datacentric or nodecentric
        self.paradigm = paradigm

        self.transmit_reading_task = None
        self.process_dgram_task = None
        self.purge_gradients_task = None

        self.transmit_reader = None
        self.transmit_writer = None
        self.gradient_reader = None
        self.gradient_writer = None


        if self.paradigm == Paradigm.DATACENTRIC.value:
            self.gradients = {}
            self.has_gradients = asyncio.Event()


    async def initialise_streams(self):
        """
        Set up asyncio streams to make API calls
        """

        await super().initialise_management_streams()

        await super().initialise_res_streams()

        self.transmit_reader, self.transmit_writer = await self.iot_device.get_iot_device_conn()

        if self.paradigm == Paradigm.DATACENTRIC.value:
            self.gradient_reader, self.gradient_writer = await self.iot_device.get_iot_device_conn()
        

    async def start_sensor(self, reading_interval, no_of_readings, res_interval, **kwargs):
        """
        Start asyncio tasks that the sensor performs
        """
        
        self.running = True
        self.socket = await self.iot_device.create_socket(self.app_port, self.management_reader, self.management_writer)


        self.transmit_reading_task = asyncio.create_task(self.transmit_reading(reading_interval, no_of_readings))

        if self.paradigm == Paradigm.DATACENTRIC.value:
            self.process_dgram_task = asyncio.create_task(self.process_dgram(kwargs["gradient_timeout"]))
            self.purge_gradients_task = asyncio.create_task(self.purge_gradients())

        self.res_task = asyncio.create_task(self.record_resources(res_interval))

        return self.transmit_reading_task

    async def process_dgram(self, gradient_timeout):
        """
        Parse expressions of interest in temperature ranges from the sink
        """
        try:
            while self.running:
                recv_details = await self.socket.recv(self.gradient_reader, self.gradient_writer)

                if recv_details.payload[0] != TsnMessage.REGISTER_INTEREST.value:
                    continue

                decoded_register_interest_dgram = decode_register_interest_dgram(recv_details.payload)

                if recv_details.src_id in self.gradients and self.gradients[recv_details.src_id].seq_no >= decoded_register_interest_dgram["seq_no"]:
                    continue

                self.gradients[recv_details.src_id] = Gradient(decoded_register_interest_dgram["lower"], decoded_register_interest_dgram["upper"], decoded_register_interest_dgram["seq_no"], time.time() + gradient_timeout)
                self.has_gradients.set()
        except asyncio.CancelledError:
            pass

    async def purge_gradients(self):
        """
        Remove gradients that are timed out
        """
        try:
            while self.running:

                # do not run unless this sensor has gradients
                await self.has_gradients.wait()

                now = time.time()
                next_timeout = None
                gradients = {}

                for sink in self.gradients:
                    if self.gradients[sink].timeout > now:
                        gradients[sink] = self.gradients[sink]
                        if next_timeout is None or gradients[sink].timeout < next_timeout:
                            next_timeout = gradients[sink].timeout

                if len(gradients) == 0:
                    self.has_gradients.clear()
                    continue

                await asyncio.sleep(next_timeout - now)
        except asyncio.CancelledError:
            pass

    async def close_sensor(self):
        """
        Stop asyncio tasks that sensor is performing
        """
        self.running = False

        if self.transmit_reading_task is not None:
            await self.transmit_reading_task

        if self.purge_gradients_task is not None:
            self.purge_gradients_task.cancel()
            await self.purge_gradients_task

        if self.process_dgram_task is not None:
            self.process_dgram_task.cancel()
            await self.process_dgram_task

        await self.cancel_resources_task()


        await self.socket.close(self.management_reader, self.management_writer)
        await self.iot_device.quit(self.management_reader, self.management_writer)

        if self.transmit_writer is not None:
            self.transmit_writer.close()

        if self.gradient_writer is not None:
            self.gradient_writer.close()

        self.close_streams()

        del self

    async def transmit_reading(self, interval, no_of_readings):
        """
        Transmit temperature readings to the sink
        """

        while self.running:

            # send reading between 0 and 49 degrees
            temp = random.randint(0,49)
            temp_dgram = get_temp_dgram(temp,self.seq_no)

            if self.paradigm == Paradigm.NODECENTRIC.value:
                await self.socket.send(self.sink_id, self.app_port, temp_dgram, self.transmit_reader, self.transmit_writer)
                self.seq_no += 1

            else:
                self.seq_no += 1
                for sink in self.gradients:
                    # for datacentric, only send if within desired range
                    if temp >= self.gradients[sink].lower and temp <= self.gradients[sink].upper:
                        await self.socket.send(self.sink_id, self.app_port, temp_dgram, self.transmit_reader, self.transmit_writer)
                        

            # stop once all readings have been sent
            if self.seq_no >= no_of_readings:
                return

            await asyncio.sleep(interval)

            # same again but now temperature in the range of 50 to 99
            temp = random.randint(50, 99)
            temp_dgram = get_temp_dgram(temp, self.seq_no)

            if self.paradigm == Paradigm.NODECENTRIC.value:
                await self.socket.send(self.sink_id, self.app_port, temp_dgram, self.transmit_reader, self.transmit_writer)
                self.seq_no += 1

            else:
                self.seq_no += 1
                for sink in self.gradients:
                    if temp >= self.gradients[sink].lower and temp <= self.gradients[sink].upper:
                        await self.socket.send(self.sink_id, self.app_port, temp_dgram, self.transmit_reader, self.transmit_writer)
                        

            if self.seq_no >= no_of_readings:
                return

            await asyncio.sleep(interval)


