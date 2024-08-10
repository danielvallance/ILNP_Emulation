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
import math
import time

sys.path.append("../../../")
sys.path.append("..")
from emulation_api import *
from tsn_utilities import *
from utilities import *
from ReceivedAppData import ReceivedAppData
from BaseIoT import BaseIoT


class Sink(BaseIoT):
    """
    Class representing sink in temperature sensor network
    """
    def __init__(self, iot, app_port, paradigm):
        BaseIoT.__init__(self, iot, app_port)

        self.received_readings = {}
        self.delays = {}

        # nodecentric or datacentric
        self.paradigm = paradigm

        self.process_readings_task = None
        self.transmit_interest_task = None

        self.temp_reader = None
        self.temp_writer = None
        self.interest_reader = None
        self.interest_writer = None

        if paradigm == Paradigm.DATACENTRIC.value:
            self.seq_no = 0

    async def initialise_streams(self):
        """
        Initialise asyncio streams to make API calls
        """
        await super().initialise_management_streams()

        await super().initialise_res_streams()

        self.temp_reader, self.temp_writer = await self.iot_device.get_iot_device_conn()
    
        if self.paradigm == Paradigm.DATACENTRIC.value:
            self.interest_reader, self.interest_writer = await self.iot_device.get_iot_device_conn()


    async def transmit_interest(self, interval):
        """
        Regularly broadcast that this sink is intereted in readings between 0 and 49 degrees inclusive
        """

        while self.running:

            interest_dgram = get_register_interest_dgram(0,49,self.seq_no)
            self.seq_no += 1
            await self.socket.flood(self.app_port, interest_dgram, self.interest_reader, self.interest_writer)

            await asyncio.sleep(interval)



    async def start_sink(self, res_interval, **kwargs):
        """
        Start asyncio tasks that this sink performs
        """

        self.running = True
        self.socket = await self.iot_device.create_socket(self.app_port, self.management_reader, self.management_writer)

        self.process_readings_task = asyncio.create_task(self.process_readings())

        self.res_task = asyncio.create_task(self.record_resources(res_interval))

        if self.paradigm == Paradigm.DATACENTRIC.value:
            self.transmit_interest_task = asyncio.create_task(self.transmit_interest(kwargs["gradient_interval"]))

    async def close_sink(self):
        """
        Stop the asyncio tasks associated with this sink
        """
        self.running = False

        if self.process_readings_task is not None:
            self.process_readings_task.cancel()
            await self.process_readings_task

        if self.transmit_interest_task is not None:
            await self.transmit_interest_task

        await self.cancel_resources_task()

        await self.socket.close(self.management_reader, self.management_writer)
        await self.iot_device.quit(self.management_reader, self.management_writer)

        if self.interest_writer is not None:
            self.interest_writer.close()

        if self.temp_writer is not None:
            self.temp_writer.close()

        self.close_streams()

        del self

    async def process_readings(self):
        """
        Process received temperature readings
        """
        try:
            while self.running:

                recv_details = await self.socket.recv(self.temp_reader, self.temp_writer)

                decoded_temp_dgram = decode_temp_dgram(recv_details.payload)
                print("Received " + str(decoded_temp_dgram) + " from " + str(recv_details.src_id))

                if recv_details.src_id not in self.received_readings:
                    self.received_readings[recv_details.src_id] = set()

                # record that this sequence number was received from the source sensor
                self.received_readings[recv_details.src_id].add(decoded_temp_dgram["seq_no"])

                if recv_details.src_id not in self.delays:
                    self.delays[recv_details.src_id] = list()

                # record delay
                self.delays[recv_details.src_id].append(math.floor(time.time_ns()/1000000) - decoded_temp_dgram["milliseconds"])
        except asyncio.CancelledError:
            pass

    def get_received_readings(self):
        return self.received_readings

    def get_delays(self):
        return self.delays