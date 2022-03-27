#! env python3

from __future__ import annotations

import typing
import io

from . import configurable
from . import resource
from . import file

class YumPackageLoader(resource.Resource):
    """Resource representing an installation of a Yum package on an instance"""
    yum_repos: configurable.Var[typing.Dict[str, str]]
    package_names: configurable.Var[typing.List[str]]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.yum_repos = configurable.Var(self, 'yum_repos')
        self.package_names = configurable.Var(self, 'package_names')
        self.installed:typing.List[str] = []
        self.instance = resource.Ref[resource.Instance](self, 'instance')

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.instance and self.yum_repos and self.package_names:
            for repo_name, repo_url in (self.yum_repos()).items():
                loader_remote = file.WebResource([ *(self.path()), repo_name ])
                loader_remote.url.select(repo_url)
                loader_image = file.Image()
                loader_image.GetFromWeb(loader_remote)
                print(f"{self} : loading yum repository {repo_name} into instance {self.instance}")
                self.instance().execute(['sudo', 'bash', '-'], 60, stdin=loader_image.contents())
            for package_name in self.package_names():
                if package_name not in self.installed:
                    print(f"{self} : installing yum package {package_name} on instance {self.instance}")
                    self.instance().execute(['sudo', 'yum', 'install', '-y', package_name ], 60)
                    self.installed.append(package_name)

    def down(self, phase: resource.Phase):
        if self.package_names and self.instance:
            package_order = list(self.package_names())
            package_order.reverse()

            for package_name in package_order:
                if package_name in self.installed:
                    print(f"{self}.down : removing yum package {package_name} from instance {self.instance}")
                    self.instance().execute(['sudo', 'yum', 'remove', '-y', package_name ], 60)
                    self.installed.remove(package_name)
