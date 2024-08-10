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


import argparse
import sys
import asyncio
import time
import traceback

sys.path.append("../..")
sys.path.append("..")

from emulation_api import *
from constants import *
from Sink import *
from Animal import *
from Router import *
from ReceivedAppData import ReceivedAppData
from get_yaml_dict import get_yaml_dict

async def main(config_file,net_protocol,run):

    # create topology
    iots = await create_topology(config_file, net_protocol)

    routers = {}
    locator_list = []

    settings_dict = get_yaml_dict(config_file)

    print("Settings dict: " + str(settings_dict))

    # create sink object
    sink = Sink(iots["sink"], settings_dict["app_port"])
    await sink.initialise_streams()

    locator_list.extend(await sink.iot_device.get_locs(sink.management_reader, sink.management_writer))

    print("Sink: " + str(sink))

    for router_name in iots:

        if router_name in ["sink", "animal"]:
            continue

        # create router object
        routers[router_name] = Router(iots[router_name], settings_dict["app_port"])
        await routers[router_name].initialise_streams()

        locator_list.extend(await routers[router_name].iot_device.get_locs(routers[router_name].management_reader, routers[router_name].management_writer))

    # create animal object
    animal = Animal(iots["animal"], settings_dict["app_port"])
    await animal.initialise_streams()

    animal_id = await animal.iot_device.get_id(animal.query_reader, animal.query_writer)

    print("Animal id: " + str(animal_id))

    # start animal object
    await animal.start_animal(locator_list, settings_dict["mobility_interval"], settings_dict["reporting_interval"])

    # start routers
    for router_name in routers:
        await routers[router_name].start_router(settings_dict["reporting_interval"])

    # start sink
    transmit_queries_task = await sink.start_sink(settings_dict["reporting_interval"], settings_dict["sink_query_interval"], animal_id, settings_dict["queries_to_send"])

    # wait for sink to send all queries
    await transmit_queries_task

    # wait a bit longer for propagation delay etc.
    await asyncio.sleep(settings_dict["final_wait"])

    # writing to file

    resolved_queries = sink.get_resolved_queries()
    outstanding_queries = sink.get_outstanding_queries()
    resources_list = animal.resources_list
    overhead_lists = [sink.overhead_list] + [animal.overhead_list] + [routers[router_name].overhead_list for router_name in routers]


    print(resolved_queries)
    print(outstanding_queries)
    print(resources_list)
    print(overhead_lists)

    data_dir = "../../../data/animal_tracker/data/"

    if run == 1:
        several_run_mode = "w+"
    else:
        several_run_mode = "a"


    if net_protocol == NetProtocol.ILNP.value:
        net_prefix = "ilnp"
    else:
        net_prefix = "ipv6"

    cpu_list = [entry["cpu_time"] - resources_list[0]["cpu_time"] for entry in resources_list]
    with open(data_dir + net_prefix + "_cpu_single_run", "w+") as cpufile:
        for i in range(len(cpu_list)):
            cpufile.write(f"{i} {cpu_list[i]}\n")

    rss_list = [entry["rss"] for entry in resources_list]
    with open(data_dir + net_prefix + "_rss_single_run", "w+") as rssfile:
        for i in range(len(rss_list)):
            rssfile.write(f"{i} {rss_list[i]}\n")

    vmem_list = [entry["virtual_mem"] for entry in resources_list]
    with open(data_dir + net_prefix + "_virtual_mem_single_run", "w+") as virtual_mem_file:
        for i in range(len(vmem_list)):
            virtual_mem_file.write(f"{i} {vmem_list[i]}\n")

    sink_overhead_list = sink.overhead_list
    app_bytes_received = [0] + [
        sink_overhead_list[i + 1]["app_bytes_recvd"] - sink_overhead_list[i]["app_bytes_recvd"] for i in
        range(len(sink_overhead_list) - 1)]
    with open(data_dir + net_prefix + "_appbytes_single_run", "w+") as appbytesfile:
        for i in range(len(app_bytes_received)):
            appbytesfile.write(f"{i} {app_bytes_received[i]}\n")

    max_overhead_len = max([len(overhead_list) for overhead_list in overhead_lists])

    ilnp_dgrams = [0 for i in range(max_overhead_len)]
    app_dgrams = [0 for i in range(max_overhead_len)]
    ilnp_bytes = [0 for i in range(max_overhead_len)]
    app_bytes = [0 for i in range(max_overhead_len)]

    for overhead_list in overhead_lists:
        for i in range(len(overhead_list)):
            if i > 0:
                ilnp_dgrams[i] += overhead_list[i]["ilnp_dgrams_sent"]
                app_dgrams[i] += overhead_list[i]["app_dgrams_sent"]
                ilnp_bytes[i] += overhead_list[i]["ilnp_bytes_sent"]
                app_bytes[i] += overhead_list[i]["app_bytes_sent"]


                ilnp_dgrams[i] -= overhead_list[i - 1]["ilnp_dgrams_sent"]
                app_dgrams[i] -= overhead_list[i - 1]["app_dgrams_sent"]
                ilnp_bytes[i] -= overhead_list[i - 1]["ilnp_bytes_sent"]
                app_bytes[i] -= overhead_list[i - 1]["app_bytes_sent"]

    with open(data_dir + net_prefix + "_packetoverheads_single_run", "w+") as packetoverheadsfile:
        for i in range(len(ilnp_dgrams)):
            if app_dgrams[i] == 0:
                packetoverheadsfile.write(f"{i} 0\n")
            else:
                packetoverheadsfile.write(f"{i} {ilnp_dgrams[i] / app_dgrams[i]}\n")

    with open(data_dir + net_prefix + "_byteoverheads_single_run", "w+") as byteoverheadsfile:
        for i in range(len(ilnp_bytes)):
            if app_bytes[i] == 0:
                byteoverheadsfile.write(f"{i} 0\n")
            else:
                byteoverheadsfile.write(f"{i} {ilnp_bytes[i] / app_bytes[i]}\n")


    with open(data_dir + net_prefix + "_request_latencies_several_runs", several_run_mode) as latencyfile:
        for i in resolved_queries:
            latencyfile.write(str(resolved_queries[i]))
            latencyfile.write("\n")


    with open(data_dir + net_prefix + "_querysuccess_several_runs", several_run_mode) as successratefile:
        successratefile.write(str((len(resolved_queries) / settings_dict["queries_to_send"]) * 100))
        successratefile.write("\n")

    with open(data_dir + net_prefix + "_virtual_mem_several_runs", several_run_mode) as vmem_several_file:
        vmem_several_file.write(f'{max(vmem_list)}\n')

    with open(data_dir + net_prefix + "_rss_several_runs", several_run_mode) as rss_several_file:
        rss_several_file.write(f'{max(rss_list)}\n')

    with open(data_dir + net_prefix + "_cpu_several_runs", several_run_mode) as cpu_several_file:
        cpu_several_file.write(f'{cpu_list[-1]}\n')

    with open(data_dir + net_prefix + "_packetoverheads_several_runs", several_run_mode) as packetoverheads_several_file:
        packetoverheads_several_file.write(f'{sum(ilnp_dgrams) / sum(app_dgrams)}\n')

    with open(data_dir + net_prefix + "_byteoverheads_several_runs", several_run_mode) as byteoverheads_several_file:
        byteoverheads_several_file.write(f'{sum(ilnp_bytes) / sum(app_bytes)}\n')

    with open(data_dir + net_prefix + "_appbytes_several_runs", several_run_mode) as app_bytes_several_file:
        app_bytes_several_file.write(f'{sum(app_bytes_received)}\n')

    await close_devices(animal, sink, routers)



async def close_devices(animal, sink, routers):
    if sink:
        await sink.close_sink()
    if animal:
        await animal.close_animal()
    for router_name in routers:
        await routers[router_name].close_router()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file")
    parser.add_argument("net_protocol", choices=["ilnp", "ipv6"])
    parser.add_argument("runs", type = int)
    args = parser.parse_args()

    if args.net_protocol == "ilnp":
        net_protocol = NetProtocol.ILNP.value
    else:
        net_protocol = NetProtocol.IPv6.value

    for i in range(args.runs):
        asyncio.run(main(args.config_file, net_protocol, i + 1))
