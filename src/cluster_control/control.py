#! env python3

from __future__ import annotations

import typing
import abc

import json
import os
import sys

script_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_path)

from . import configurable
from . import resource
from . import file
from . import formats
from . import package_manager
from . import ec2_cloud
from . import ec2_express_cluster
from . import code_repository
from . import ssl_security

repo_path = script_path.split('/')
repo_path = repo_path[0:len(repo_path)-1]
repo_path = '/'.join(repo_path)

import argparse

parser = argparse.ArgumentParser(description='Spinup cloud cluster')
parser.add_argument('verb', type=str, choices=['create', 'CREATE', 'configure', 'CONFIGURE', 'up', 'UP', 'down', 'DOWN', 'watch', 'WATCH', 'ip', 'IP', 'ssh', 'SSH', 'stop', 'STOP', 'start', 'START', 'pull', 'PULL', 'get', 'GET', 'put', 'PUT', 'build', 'BUILD'],
                    help='command verbs: bring cluster UP, take cluster DOWN, WATCH server logs, show service IP address, open SSH shell on service instance')
parser.add_argument('-c', '--config', type=str, help='path to configuration file', required=True)
args, unknown = parser.parse_known_args()

if args.verb in ('create', 'CREATE'):
    parser.add_argument('resource_name', type=str, help='name of the new resource instance')
    args, unknown = parser.parse_known_args()
    if args.resource_name is None:
        raise RuntimeError(f"Must provide a resource_name when creating a resource")
    config = ec2_express_cluster.ManageCluster([ args.resource_name ])
else:
    with open(args.config, 'rt') as fp:
        as_json = json.load(fp, object_hook=formats.json_as_python_set)
        reader = formats.JSONReader(sys.modules[__name__], as_json)
        config = reader.read()
    if not isinstance(config, resource.Resource):
        raise RuntimeError(f"Config file {args.c} is not a resource, it is a {config}")

all_vars: typing.Set[configurable.Var] = set()
all_resources: typing.Set[resource.Resource] = set()
config.collect(all_vars, all_resources)
for var in all_vars:
    name = '-'.join(var.path()[1:])
    if name == '':
        print(f"DEBUG: malformed {var}")
    else:
        parser.add_argument('--'+name, type=str)

args, unknown = parser.parse_known_args()

for var in all_vars:
    name = '-'.join(var.path()[1:])
    if hasattr(args, name) and getattr(args, name) is not None:
        getattr(config, name).select(getattr(args, name))

persistor = resource.PersistInFile(args.config, config)

if args.verb in ('up', 'UP'):
    with resource.Phase(f'cluster_control UP {config}', persistor, config) as phase:
        config.elaborate(phase)
        config.up(phase)
        
elif args.verb in ('down', 'DOWN'):
    with resource.Phase(f'cluster_control DOWN {config}', persistor, config) as phase:
        config.down(phase)
elif args.verb in ('ssh', 'SSH'):
    if not hasattr(config, 'shell'):
        raise RuntimeError(f'ssh command is not supported for {config}')
    with resource.Phase(f'cluster_control SSH {config}', persistor, config) as phase:
        getattr(config, 'shell')(phase)
elif args.verb in ('watch', 'WATCH'):
    if not hasattr(config, 'watch'):
        raise RuntimeError(f'watch command is not supported for {config}')
    with resource.Phase(f'cluster_control WATCH {config}', persistor, config) as phase:
        getattr(config, 'watch')(phase)
else:
    persistor.save()

# elif args.verb in ('watch', 'WATCH'):
#     config.watch()
# elif args.verb in ('ip', 'IP'):
#     config.ip()
# elif args.verb in ('ssh', 'SSH'):
#     config.ssh()
# elif args.verb in ('stop', 'STOP'):
#     config.stop()
# elif args.verb in ('start', 'START'):
#     config.start()
# elif args.verb in ('pull', 'PULL'):
#     config.pull()
# elif args.verb in ('build', 'BUILD'):
#     config.build()
# elif args.verb in ('get', 'GET'):
#     parser = argparse.ArgumentParser(description='GET file from instance')
#     parser.add_argument('remote_path', type=str)
#     parser.add_argument('local_path', type=str)
#     verb_args = parser.parse_args(unknown)
#     config.get(verb_args.remote_path, verb_args.local_path)
# elif args.verb in ('put', 'PUT'):
#     parser = argparse.ArgumentParser(description='PUT file to instance')
#     parser.add_argument('local_path', type=str)
#     parser.add_argument('remote_path', type=str)
#     verb_args = parser.parse_args(unknown)
#     config.put(verb_args.local_path, verb_args.remote_path)
