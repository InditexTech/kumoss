# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.template_interface import ITemplate
from src.infrastructure.templates._aws import AWSTemplateAdapter
from src.infrastructure.templates._azure import AzureTemplateAdapter
from src.infrastructure.templates._gcp import GCPTemplateAdapter
from src.infrastructure.templates._oci import OCITemplateAdapter
from src.infrastructure.templates._kubernetes import KubernetesTemplateAdapter
from src.infrastructure.templates._common import CommonTemplateAdapter
from src.shared.constants import TemplateProvider


class TemplateFactory:
    def __init__(
        self,
        template_provider: TemplateProvider,
        cwd: str,
    ):
        self.__template_prv = template_provider
        self.__cwd = cwd

    def get(self) -> ITemplate:
        """Get a template provider
        :return: the corresponding template adapter
        """
        match self.__template_prv:
            case TemplateProvider.AZURE:
                return AzureTemplateAdapter(cwd=self.__cwd)
            case TemplateProvider.GCP:
                return GCPTemplateAdapter(cwd=self.__cwd)
            case TemplateProvider.AWS:
                return AWSTemplateAdapter(cwd=self.__cwd)
            case TemplateProvider.OCI:
                return OCITemplateAdapter(cwd=self.__cwd)
            case TemplateProvider.KUBERNETES:
                return KubernetesTemplateAdapter(cwd=self.__cwd)
            case TemplateProvider.COMMON:
                return CommonTemplateAdapter(cwd=self.__cwd)
            case _:
                raise NotImplementedError()


if __name__ == "__main__":
    factory = TemplateFactory(TemplateProvider.GCP, cwd=".")
    # prompt = factory.get().render_iac_generator(resources=["keyvault"], abbreviations=["sta"])
    prompt = factory.get().render_iac_generator(
        resources=["service_account"], abbreviations=[]
    )
    print(prompt)
