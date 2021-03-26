#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

import resource
import blob

class YumPackageLoader(resource.Resource):
    """Resource representing an installation of a Yum package on an instance"""
    def __init__(self, instance: resource.Instance=None, yum_repos: Dict[str, str]=None, package_names:List[str]=None):
        self.instance = instance
        self.yum_repos = yum_repos
        self.package_names = package_names
        self.installed:List[str] = []

    def plan(self):
        pass

    def up(self, top):
        for repo_name, repo_url in self.yum_repos.items():
            script_file = blob.File(repo_name, 'sh', repo_url)
            script_file.plan()
            script_file.up(top)
            script_file.write()
            print(f"{self.__class__.__qualname__}.up : loading yum repository {repo_name} into instance {self.instance.name}")
            self.instance.execute(['sudo', 'bash', '-'], 60, stdin=script_file.open())
        for package_name in self.package_names:
            if package_name not in self.installed:
                print(f"{self.__class__.__qualname__}.up : installing yum package {package_name} on instance {self.instance.name}")
                self.instance.execute(['sudo', 'yum', 'install', '-y', package_name ], 60)
                self.installed.append(package_name)
                top.save()

    def down(self, top):
        package_order = list(self.package_names)
        package_order.reverse()
        for package_name in package_order:
            if package_name in self.installed:
                print(f"{self.__class__.__qualname__}.down : removing yum package {package_name} from instance {self.instance.name}")
                self.instance.execute(['sudo', 'yum', 'remove', '-y', package_name ], 60)
                self.installed.remove(package_name)
                top.save()

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('instance')
        visitor.inline('yum_repos')
        visitor.inline('package_names')
        visitor.inline('installed')
        visitor.endObject(self)
