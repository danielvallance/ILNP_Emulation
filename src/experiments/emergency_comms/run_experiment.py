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
sys.path.append("../")

from emulation_api import *
from constants import *
from Mobile import *
from ReceivedAppData import ReceivedAppData
from get_yaml_dict import get_yaml_dict


async def main(config_file,net_protocol,run):

    # create topology
    iots = await create_topology(config_file, net_protocol)

    mobiles = {}
    locators = {}
    initial_locs = {}
    all_locs = set()

    settings_dict = get_yaml_dict(config_file)

    print("Settings dict: " + str(settings_dict))

    receiver_id = None

    for mobile_name in iots:

        if mobile_name == "receiver":
            role = Roles.RECEIVER.value
        elif mobile_name == "sender":
            role = Roles.SENDER.value
        else:
            role = Roles.STANDARD.value

        # create mobile object
        mobiles[mobile_name] = Mobile(iots[mobile_name], settings_dict["app_port"], role)
        await mobiles[mobile_name].initialise_streams()

        current_mobile = mobiles[mobile_name]

        # add locators to set of all locators
        initial_locs[mobile_name] = await current_mobile.iot_device.get_locs(current_mobile.management_reader, current_mobile.management_writer)
        all_locs.update(initial_locs[mobile_name])

        inv_locs = await current_mobile.iot_device.get_inv_locs(current_mobile.management_reader, current_mobile.management_writer)
        print(mobile_name + "'s invariant locs: " + str(inv_locs))

        if mobile_name == "receiver":
            receiver_id = await current_mobile.iot_device.get_id(current_mobile.management_reader, current_mobile.management_writer)

        # add invariant locators to previous mobiles' sets of invariant locators of mobiles after them
        for prev_mobile in mobiles:
            if prev_mobile == mobile_name:
                continue
            if prev_mobile not in locators:
                locators[prev_mobile] = set()
            locators[prev_mobile].update(inv_locs)

    # start mobiles
    for mobile_name in mobiles:
        if mobile_name in ["sender", "receiver"]:
            continue

        await mobiles[mobile_name].start_mobile(settings_dict["reporting_interval"], list(locators[mobile_name]), settings_dict["mobility_interval"])

    # start receiver mobile
    await mobiles["receiver"].start_mobile(settings_dict["reporting_interval"],  all_locs, settings_dict["mobility_interval"])

    # start sending mobile
    sending_task = await mobiles["sender"].start_mobile(settings_dict["reporting_interval"], all_locs, settings_dict[
            "mobility_interval"], rate=settings_dict["flow_rate"], receiver_id=receiver_id, dgrams_to_send=settings_dict["dgrams_to_send"])

    # wait for sender to finish
    await sending_task

    # wait a bit longer for propagation delay etc
    await asyncio.sleep(settings_dict["final_wait"])

    # write data to files

    delays = mobiles["receiver"].delays
    resources_list = mobiles["sender"].resources_list
    overhead_lists = [mobiles[mobile_name].overhead_list for mobile_name in mobiles]

    print(delays)
    print(resources_list)
    print(overhead_lists)

    if run == 1:
        several_run_mode = "w+"
    else:
        several_run_mode = "a"

    data_dir = "../../../data/emergency_comms/data/"

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

    recv_overhead_list = mobiles["receiver"].overhead_list
    app_bytes_received = [0] + [
        recv_overhead_list[i + 1]["app_bytes_recvd"] - recv_overhead_list[i]["app_bytes_recvd"] for i in
        range(len(recv_overhead_list) - 1)]
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

    delays = mobiles["receiver"].delays

    with open(data_dir + net_prefix + "_app_delay_several_runs", several_run_mode) as delayfile:

        for i in delays:
            delayfile.write(str(delays[i]))
            delayfile.write("\n")

    with open(data_dir + net_prefix + "_app_delivery_rate_several_runs", several_run_mode) as delivfile:
        delivfile.write(str((len(delays)/settings_dict["dgrams_to_send"]) * 100))

        delivfile.write("\n")

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

    await close_devices(mobiles)

async def close_devices(mobiles):
    for mobile_name in mobiles:
        await mobiles[mobile_name].close_mobile()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file")
    parser.add_argument("net_protocol", choices=["ilnp", "ipv6"])
    parser.add_argument("runs",type=int)
    args = parser.parse_args()

    if args.net_protocol == "ilnp":
        net_protocol = NetProtocol.ILNP.value
    else:
        net_protocol = NetProtocol.IPv6.value


    for i in range(args.runs):
        asyncio.run(main(args.config_file, net_protocol,i+1))
