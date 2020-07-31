"""Launching tool for DGL distributed training"""
import os
import stat
import sys
import subprocess
import argparse
import signal
import logging
import time
from threading import Thread

def execute_remote(cmd, ip, thread_list):
    """execute command line on remote machine via ssh"""
    cmd = 'ssh -o StrictHostKeyChecking=no ' + ip + ' \'' + cmd + '\''
    # thread func to run the job
    def run(cmd):
        subprocess.check_call(cmd, shell = True)

    thread = Thread(target = run, args=(cmd,))
    thread.setDaemon(True)
    thread.start()
    thread_list.append(thread)

def submit_jobs(args, udf_command):
    """Submit distributed jobs (server and client processes) via ssh"""
    hosts = []
    thread_list = []
    server_count_per_machine = 0
    ip_config = args.workspace + '/' + args.ip_config
    with open(ip_config) as f:
        for line in f:
            ip, port, count = line.strip().split(' ')
            port = int(port)
            count = int(count)
            server_count_per_machine = count
            hosts.append((ip, port))
    assert args.num_client % len(hosts) == 0
    client_count_per_machine = int(args.num_client / len(hosts))
    # launch server tasks
    server_cmd = 'DGL_ROLE=server'
    server_cmd = server_cmd + ' ' + 'DGL_NUM_CLIENT=' + str(args.num_client)
    server_cmd = server_cmd + ' ' + 'DGL_CONF_PATH=' + str(args.part_config)
    server_cmd = server_cmd + ' ' + 'DGL_IP_CONFIG=' + str(args.ip_config)
    for i in range(len(hosts)*server_count_per_machine):
        ip, _ = hosts[int(i / server_count_per_machine)]
        cmd = server_cmd + ' ' + 'DGL_SERVER_ID=' + str(i)
        cmd = cmd + ' ' + udf_command
        cmd = 'cd ' + str(args.workspace) + '; ' + cmd
        execute_remote(cmd, ip, thread_list)
    # launch client tasks
    client_cmd = 'DGL_DIST_MODE="distributed" DGL_ROLE=client'
    client_cmd = client_cmd + ' ' + 'DGL_NUM_CLIENT=' + str(args.num_client)
    client_cmd = client_cmd + ' ' + 'DGL_CONF_PATH=' + str(args.part_config)
    client_cmd = client_cmd + ' ' + 'DGL_IP_CONFIG=' + str(args.ip_config)
    if os.environ.get('OMP_NUM_THREADS') is not None:
        client_cmd = client_cmd + ' ' + 'OMP_NUM_THREADS=' + os.environ.get('OMP_NUM_THREADS')
    if os.environ.get('PYTHONPATH') is not None:
        client_cmd = client_cmd + ' ' + 'PYTHONPATH=' + os.environ.get('PYTHONPATH')

    torch_cmd = '-m torch.distributed.launch'
    torch_cmd = torch_cmd + ' ' + '--nproc_per_node=' + str(client_count_per_machine)
    torch_cmd = torch_cmd + ' ' + '--nnodes=' + str(len(hosts))
    torch_cmd = torch_cmd + ' ' + '--node_rank=' + str(0)
    torch_cmd = torch_cmd + ' ' + '--master_addr=' + str(hosts[0][0])
    torch_cmd = torch_cmd + ' ' + '--master_port=' + str(1234)

    for node_id, host in enumerate(hosts):
        ip, _ = host
        new_torch_cmd = torch_cmd.replace('node_rank=0', 'node_rank='+str(node_id))
        new_udf_command = udf_command.replace('python3', 'python3 ' + new_torch_cmd)
        cmd = client_cmd + ' ' + new_udf_command
        cmd = 'cd ' + str(args.workspace) + '; ' + cmd
        execute_remote(cmd, ip, thread_list)

    for thread in thread_list:
        thread.join()

def main():
    parser = argparse.ArgumentParser(description='Launch a distributed job')
    parser.add_argument('--workspace', type=str,
                        help='Path of user directory of distributed tasks. \
                        This is used to specify a destination location where \
                        the contents of current directory will be rsyncd')
    parser.add_argument('--num_client', type=int,
                        help='Total number of client processes in the cluster')
    parser.add_argument('--part_config', type=str,
                        help='The file (in workspace) of the partition config')
    parser.add_argument('--ip_config', type=str,
                        help='The file (in workspace) of IP configuration for server processes')
    args, udf_command = parser.parse_known_args()
    assert len(udf_command) == 1, 'Please provide user command line.'
    assert args.num_client > 0, '--num_client must be a positive number.'
    udf_command = str(udf_command[0])
    if 'python' not in udf_command:
        raise RuntimeError("DGL launch can only support: python ...")
    submit_jobs(args, udf_command)

def signal_handler(signal, frame):
    logging.info('Stop launcher')
    sys.exit(0)

if __name__ == '__main__':
    fmt = '%(asctime)s %(levelname)s %(message)s'
    logging.basicConfig(format=fmt, level=logging.INFO)
    signal.signal(signal.SIGINT, signal_handler)
    main()
