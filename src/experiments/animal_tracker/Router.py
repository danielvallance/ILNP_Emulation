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

class Router(BaseIoT):

    """
    Object that just performs routing of tracking queries
    """

    def __init__(self, iot, app_port):
        BaseIoT.__init__(self, iot, app_port)


    async def initialise_streams(self):
        """
        Sets up asyncio streams used for API calls
        """
        await super().initialise_management_streams()

        await super().initialise_res_streams()




    async def start_router(self, res_interval):
        """
        Starts asyncio tasks
        """
        self.running = True

        self.res_task = asyncio.create_task(self.record_resources(res_interval))




    async def close_router(self):
        """
        Stops asyncio tasks it was performing
        """
        self.running = False

        await self.cancel_resources_task()

        await self.iot_device.quit(self.management_reader, self.management_writer)

        self.close_streams()
        del self


