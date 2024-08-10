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

sys.path.append("../..")
sys.path.append("..")

from emulation_api import *
from constants import *
from Sink import *
from Sensor import *
from ReceivedAppData import ReceivedAppData
from get_yaml_dict import get_yaml_dict


async def main(config_file, paradigm, net_protocol, run):

    # create the initial topology
    iots = await create_topology(config_file, net_protocol)
    id_indices = {}
    ids_to_names = {}

    settings_dict = get_yaml_dict(config_file)


    print("Settings dict: " + str(settings_dict))

    # create sink object
    sink = Sink(iots["sink"], settings_dict["app_port"], paradigm)
    await sink.initialise_streams()
    print("Sink: " + str(sink))

    sink_id = await sink.iot_device.get_id(sink.management_reader, sink.management_writer)
    print("Sink id: " + str(sink_id))

    sensors = {}


    for sensor_name in iots:

        if sensor_name == "sink":
            continue

        # create sensor objects
        sensors[sensor_name] = Sensor(iots[sensor_name], sink_id, settings_dict["app_port"], paradigm)
        await sensors[sensor_name].initialise_streams()

        print(sensor_name + ": " + str(sensors[sensor_name]))

        current = sensors[sensor_name]

        current_id = await current.iot_device.get_id(current.management_reader, current.management_writer)
        ids_to_names[current_id] = sensor_name
        
        id_indices[current_id] = ord(sensor_name) - 96

        sink.delays[current_id] = []
        sink.received_readings[current_id] = set()

    # Topology now set up

    sensor_tasks = []

    # start sensors
    for sensor_name in iots:
        if sensor_name == "sink":
            continue

        sensor_tasks.append(await sensors[sensor_name].start_sensor(settings_dict["sensor_send_interval"],
                                                                        settings_dict["readings_to_send"], settings_dict["res_interval"], gradient_timeout=settings_dict["gradient_timeout"]))
    #start sink
    await sink.start_sink(settings_dict["res_interval"], gradient_interval=settings_dict["gradient_interval"])

    # wait for sensors to finish sending
    await asyncio.gather(*sensor_tasks)

    # wait a little bit more to wait for propogation delay etc.
    await asyncio.sleep(settings_dict["final_wait"])


    # write data to file
    received_readings = sink.get_received_readings()

    sink_delays = sink.get_delays()
    delay_matrix = []
    max_len = max(len(sink_delays[sensor]) for sensor in sink_delays)
    overhead_lists = [sink.overhead_list] + [sensors[sensor_name].overhead_list for sensor_name in sensors]

    for i in range(max_len):
        delay_list = ["NaN" for i in range(len(sink_delays))]

        for sensor_id in sink_delays:
            if i < len(sink_delays[sensor_id]):
                delay_list[id_indices[sensor_id]-1] = str(sink_delays[sensor_id][i])
        delay_matrix.append(delay_list)


    resources_list = sensors[settings_dict["resource_reporting_sensor"]].resources_list

    print(received_readings)

    print(resources_list)

    if run == 1:
        several_run_mode = "w+"
    else:
        several_run_mode = "a"

    if paradigm == Paradigm.NODECENTRIC.value:
        data_dir = "../../../data/nodecentric_tsn/data/"
        expected_readings = settings_dict["readings_to_send"]
    else:
        data_dir = "../../../data/datacentric_tsn/data/"
        expected_readings = settings_dict["readings_to_send"]/2


    if net_protocol == NetProtocol.ILNP.value:
        net_prefix = "ilnp"
    else:
        net_prefix = "ipv6"

    with open(data_dir + net_prefix + "_delays_several_runs", several_run_mode) as delayfile:
        for delay_list in delay_matrix:
            delayfile.write(" ".join(delay_list))
            delayfile.write("\n")

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


    with open(data_dir + net_prefix + "_delivery_rate_several_runs", several_run_mode) as deliveryratefile:
        deliv_dict = {}
        for sensor_id in received_readings:
            deliv_dict[ids_to_names[sensor_id]] = (len(received_readings[sensor_id]))/expected_readings * 100

        delivlist = [str(deliv_dict[sensor_name]) for sensor_name in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]]

        deliveryratefile.write(" ".join(delivlist))
        deliveryratefile.write("\n")




    sink_overhead_list = sink.overhead_list
    app_bytes_received = [0] + [sink_overhead_list[i+1]["app_bytes_recvd"] - sink_overhead_list[i]["app_bytes_recvd"] for i in range(len(sink_overhead_list)-1)]
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


                ilnp_dgrams[i] -= overhead_list[i-1]["ilnp_dgrams_sent"]
                app_dgrams[i] -= overhead_list[i-1]["app_dgrams_sent"]
                ilnp_bytes[i] -= overhead_list[i-1]["ilnp_bytes_sent"]
                app_bytes[i] -= overhead_list[i-1]["app_bytes_sent"]


    with open(data_dir + net_prefix + "_packetoverheads_single_run", "w+") as packetoverheadsfile:
        for i in range(len(ilnp_dgrams)):
            if app_dgrams[i] == 0:
                packetoverheadsfile.write(f"{i} NaN\n")
            else:
                packetoverheadsfile.write(f"{i} {ilnp_dgrams[i] / app_dgrams[i]}\n")


    with open(data_dir + net_prefix + "_byteoverheads_single_run", "w+") as byteoverheadsfile:
       for i in range(len(ilnp_bytes)):
            if app_bytes[i] == 0:
                byteoverheadsfile.write(f"{i} NaN\n")
            else:
                byteoverheadsfile.write(f"{i} {ilnp_bytes[i] / app_bytes[i]}\n")

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

    await close_devices(sink, sensors.values())

async def close_devices(sink, sensors):
    if sink:
        await sink.close_sink()
    for sensor in sensors:
        await sensor.close_sensor()



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file")
    parser.add_argument("paradigm", choices=["nodecentric", "datacentric"])
    parser.add_argument("net_protocol", choices=["ilnp", "ipv6"])
    parser.add_argument("runs", type = int)
    args = parser.parse_args()

    if args.paradigm == "nodecentric":
        paradigm = Paradigm.NODECENTRIC.value
    else:
        paradigm = Paradigm.DATACENTRIC.value

    if args.net_protocol == "ilnp":
        net_protocol = NetProtocol.ILNP.value
    else:
        net_protocol = NetProtocol.IPv6.value

    for i in range(args.runs):
        asyncio.run(main(args.config_file, paradigm, net_protocol, i + 1))
