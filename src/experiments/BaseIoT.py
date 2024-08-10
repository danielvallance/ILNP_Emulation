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
import asyncio

sys.path.append("../../")
from emulation_api import *
from utilities import *
from ReceivedAppData import ReceivedAppData

class BaseIoT:
    """
    Base IoT class containing methods and state common across
    all emulated IoTs in the experiments (mostly related to resource measurement)
    """
    def __init__(self, iot, app_port):

        self.app_port = app_port

        self.iot_device = iot
        self.running = False

        self.res_task = None


        self.resources_list = []
        self.overhead_list = []

        self.res_reader = None
        self.res_writer = None
        self.management_reader = None
        self.management_writer = None

        self.res_task = None



    async def record_resources(self, interval):
        """
        Adds to its record of resource and overhead data every interval
        """
        while self.running:

            self.resources_list.append(await self.get_resources())
            self.overhead_list.append(await self.get_overhead())
            await asyncio.sleep(interval)


    async def initialise_res_streams(self):
        """
        Set up asyncio streams for making resource measurement API calls
        """
        self.res_reader, self.res_writer = await self.iot_device.get_iot_device_conn()

    async def initialise_management_streams(self):
        """
        Set up asyncio streams for making API calls for the general management of this IoT
        """
        self.management_reader, self.management_writer = await self.iot_device.get_iot_device_conn()

    def close_streams(self):
        if self.management_writer is not None:
            self.management_writer.close()
        if self.res_writer is not None:
            self.res_writer.close()

    async def cancel_resources_task(self):
        if self.res_task is not None:
            await self.res_task


    async def get_overhead(self):
        """
        Make API call returning overhead stats
        """
        return await self.iot_device.get_overhead(self.res_reader, self.res_writer)

    async def get_resources(self):
        """
        Return dictionary containing results of resource consumption API calls
        """
        cpu_time = await self.iot_device.get_cpu_time(self.res_reader, self.res_writer)
        rss = await self.iot_device.get_rss(self.res_reader, self.res_writer)
        virtual_mem = await self.iot_device.get_virtual_mem(self.res_reader, self.res_writer)

        return {"cpu_time": cpu_time, "rss": rss, "virtual_mem": virtual_mem}