#! env python3

from __future__ import annotations

import typing
import abc

import json
import os
import sys

script_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_path)

from . import actions
from . import configurable
from . import resource
from . import file
from . import formats
from . import yum
from . import aws_ec2
from . import ec2_express_cluster
from . import git
from . import ssl_security

import argparse

class Controller:
    def __init__(
        self, 
        verbs: typing.List [ actions.Verb ]
    ):
        self.verbs = {}
        for verb in verbs:
            for name in verb.get_names():
                self.verbs[name] = verb

    def __call__(self):
        parser = argparse.ArgumentParser(description='Spinup cloud cluster')
        parser.add_argument('verb', type=str, choices=['create', 'configure']+list(self.verbs.keys()),
                            help='command verbs: bring cluster UP, take cluster DOWN, WATCH server logs, show service IP address, open SSH shell on service instance')
        parser.add_argument('-c', '--config', type=str, help='path to configuration file', required=True)
        args, unknown = parser.parse_known_args()

        if args.verb in ('create', 'CREATE'):
            parser.add_argument('resource_class', type=str, help='resource class to be created')
            parser.add_argument('resource_name', type=str, help='name of the new resource instance')
            args, unknown = parser.parse_known_args()
            if args.resource_name is None:
                raise RuntimeError(f"Must provide a resource_name when creating a resource")
            reader = formats.JSONReader(sys.modules[__name__], {})
            config = reader.instantiate(args.resource_class.split('.'))
            config.name = args.resource_name            
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
        seen = set()
        for var in all_vars:
            name = '-'.join(var.path()[1:])
            if name in seen:
                pass
            elif name == '':
                print(f"DEBUG: malformed {var}")
            else:
                seen.add(name)
                parser.add_argument('--'+name, type=str)

        args, unknown = parser.parse_known_args()

        for var in all_vars:
            name = '-'.join(var.path()[1:])
            if hasattr(args, name) and getattr(args, name) is not None:
                getattr(config, name).select(getattr(args, name))

        persistor = resource.PersistInFile(args.config, config)

        if args.verb in self.verbs:
            with resource.Phase(f'cluster_control {args.verb} {config}', persistor, config) as phase:
                self.verbs[args.verb](config, phase)                
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
