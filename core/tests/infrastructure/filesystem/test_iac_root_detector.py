# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from src.infrastructure.filesystem.iac_root_detector import _find_roots

GOLDEN_FIXTURE = [
    ".editorconfig",
    ".gitignore",
    "LICENSE",
    "README.md",
    "_header_/README.md",
    "aws/aws_domain_redirect/main.tf",
    "aws/aws_domain_redirect/variables.tf",
    "aws/aws_ec2_ebs_docker_host/main.tf",
    "aws/aws_ec2_ebs_docker_host/variables.tf",
    "aws/aws_ec2_ebs_docker_host/data.tf",
    "aws/aws_ec2_ebs_docker_host/outputs.tf",
    "aws/aws_ec2_ebs_docker_host/security.tf",
    "aws/aws_lambda_api/main.tf",
    "aws/aws_lambda_api/variables.tf",
    "aws/aws_lambda_api/outputs.tf",
    "aws/aws_lambda_api/example-project/package.json",
    "aws/aws_lambda_cronjob/main.tf",
    "aws/aws_lambda_cronjob/variables.tf",
    "aws/aws_mailgun_domain/main.tf",
    "aws/aws_mailgun_domain/variables.tf",
    "aws/aws_reverse_proxy/variables.tf",
    "aws/aws_reverse_proxy/cloudfront.tf",
    "aws/aws_static_site/main.tf",
    "aws/aws_vpc_msk/provider.tf",
    "aws/aws_vpc_msk/vpc.tf",
    "aws/aws_vpc_msk/terraform.tfvars",
    "aws/static_website_ssl_cloudfront_private_s3/main.tf",
    "aws/wordpress_fargate/provider.tf",
    "azure/azure_linux_docker_app_service/provider.tf",
    "azure/layers/main.tf",
    "azure/layers/variables.tf",
    "generic/docker_compose_host/main.tf",
    "google_cloud/CQRS_bigquery_memorystore/main.tf",
    "google_cloud/CQRS_bigquery_memorystore/bigquery/controls.tf",
    "google_cloud/CQRS_bigquery_memorystore/functions/gcs.tf",
    "google_cloud/camunda/main.tf",
    "google_cloud/camunda-secure/main.tf",
    "google_cloud/minecraft/main.tf",
    "google_cloud/oathkeeper/main.tf",
    "google_cloud/openresty-beyondcorp/main.tf",
    "package.json",
    "repotools/generate_readme.js",
]

EXPECTED_ROOTS = [
    "aws/aws_domain_redirect",
    "aws/aws_ec2_ebs_docker_host",
    "aws/aws_lambda_api",
    "aws/aws_lambda_cronjob",
    "aws/aws_mailgun_domain",
    "aws/aws_reverse_proxy",
    "aws/aws_static_site",
    "aws/aws_vpc_msk",
    "aws/static_website_ssl_cloudfront_private_s3",
    "aws/wordpress_fargate",
    "azure/azure_linux_docker_app_service",
    "azure/layers",
    "generic/docker_compose_host",
    "google_cloud/CQRS_bigquery_memorystore",
    "google_cloud/camunda",
    "google_cloud/camunda-secure",
    "google_cloud/minecraft",
    "google_cloud/oathkeeper",
    "google_cloud/openresty-beyondcorp",
]


class TestFindRoots(unittest.TestCase):
    def test_golden_fixture_returns_expected_roots(self):
        roots = _find_roots(GOLDEN_FIXTURE)
        self.assertEqual(roots, EXPECTED_ROOTS)

    def test_modules_segment_excluded(self):
        files = [
            "infra/main.tf",
            "infra/modules/networking/main.tf",
            "infra/modules/networking/variables.tf",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["infra"])
        self.assertNotIn("infra/modules/networking", roots)

    def test_examples_segment_excluded(self):
        files = [
            "mymodule/main.tf",
            "mymodule/examples/basic/main.tf",
            "mymodule/example/advanced/main.tf",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["mymodule"])
        self.assertNotIn("mymodule/examples/basic", roots)
        self.assertNotIn("mymodule/example/advanced", roots)

    def test_dot_terraform_excluded(self):
        files = [
            "infra/main.tf",
            ".terraform/plugins/main.tf",
            "infra/.terraform/modules/vpc/main.tf",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["infra"])

    def test_leaf_with_only_main_tf_is_kept(self):
        files = ["google_cloud/minecraft/main.tf"]
        roots = _find_roots(files)
        self.assertEqual(roots, ["google_cloud/minecraft"])

    def test_leaf_under_existing_root_is_absorbed(self):
        files = [
            "parent/main.tf",
            "parent/child/network.tf",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["parent"])

    def test_tfvars_makes_directory_a_root(self):
        files = [
            "deploy/network.tf",
            "deploy/terraform.tfvars",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["deploy"])

    def test_tfvars_json_makes_directory_a_root(self):
        files = [
            "deploy/network.tf",
            "deploy/prod.tfvars.json",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["deploy"])

    def test_empty_input(self):
        self.assertEqual(_find_roots([]), [])

    def test_no_terraform_files(self):
        files = ["README.md", "src/main.py", "package.json"]
        self.assertEqual(_find_roots(files), [])

    def test_independent_leaves_both_kept(self):
        files = [
            "a/network.tf",
            "b/compute.tf",
        ]
        roots = _find_roots(files)
        self.assertEqual(roots, ["a", "b"])
