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
sys.path.append("../")
from emulation_api import *
from animal_tracker_utilities import *
from utilities import *
from ReceivedAppData import ReceivedAppData
from BaseIoT import BaseIoT


class Sink(BaseIoT):
    """
    Object representing sink that makes queries about location of animal IoT
    """
    def __init__(self, iot, app_port):
        BaseIoT.__init__(self, iot, app_port)

        self.outstanding_queries = {}

        self.resolved_queries = {}

        self.req_no = 0


        self.process_responses_task = None
        self.transmit_queries_task = None

        self.response_reader = None
        self.response_writer = None
        self.query_reader = None
        self.query_writer = None

    async def initialise_streams(self):
        """
        Sets up asyncio streams to make API calls
        """

        await super().initialise_management_streams()

        await super().initialise_res_streams()
        self.response_reader, self.response_writer = await self.iot_device.get_iot_device_conn()
        self.query_reader, self.query_writer = await self.iot_device.get_iot_device_conn()

    async def transmit_queries(self, interval, animal_id, queries_to_send):
        """
        Task that sends queries to the animal IoT
        """

        while self.running:

            # stop once all the queries have been sent
            if self.req_no >= queries_to_send:
                return

            self.outstanding_queries[self.req_no] = math.floor(time.time_ns() / 1000000)

            print("Sending req")
            print(self.outstanding_queries[self.req_no])
            await self.socket.send(animal_id, self.app_port, get_tracking_request_dgram(self.req_no), self.query_reader, self.query_writer)
            self.req_no += 1
            await asyncio.sleep(interval)

    async def start_sink(self, res_interval, query_interval, animal_id, queries_to_send):

        """
        Start asyncio tasks that the sink performs
        """
        self.running = True
        self.socket = await self.iot_device.create_socket(self.app_port, self.management_reader, self.management_writer)


        self.res_task = asyncio.create_task(self.record_resources(res_interval))

        self.process_responses_task = asyncio.create_task(self.process_responses())

        self.transmit_queries_task = asyncio.create_task(self.transmit_queries(query_interval, animal_id, queries_to_send))

        return self.transmit_queries_task

    async def close_sink(self):
        """
        Stop asyncio tasks that the sink performs
        """

        self.running = False

        if self.process_responses_task is not None:
            self.process_responses_task.cancel()
            await self.process_responses_task

        if self.transmit_queries_task is not None:
            await self.transmit_queries_task

        await self.cancel_resources_task()

        await self.socket.close(self.management_reader, self.management_writer)
        await self.iot_device.quit(self.management_reader, self.management_writer)

        if self.response_writer is not None:
            self.response_writer.close()

        if self.query_writer is not None:
            self.query_writer.close()

        self.close_streams()

        del self

    async def process_responses(self):
        """
        Update latency and resolved query data on receiving a query response
        """
        try:
            while self.running:

                recv_details = await self.socket.recv(self.response_reader, self.response_writer)

                decoded_tracking_response_dgram = decode_tracking_response_dgram(recv_details.payload)
                print("Received " + str(decoded_tracking_response_dgram) + " from " + str(recv_details.src_id))


                self.resolved_queries[decoded_tracking_response_dgram["req_no"]] = math.floor(time.time_ns() / 1000000) - self.outstanding_queries[decoded_tracking_response_dgram["req_no"]]

                del self.outstanding_queries[decoded_tracking_response_dgram["req_no"]]


        except asyncio.CancelledError:
            return


    def get_outstanding_queries(self):
        return self.outstanding_queries

    def get_resolved_queries(self):
        return self.resolved_queries
