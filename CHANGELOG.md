# Changelog

## [1.1.0](https://github.com/InditexTech/kumoss/compare/v1.0.9...v1.1.0) (2026-11-26)


### Features

* carry the project identifier from the client to the IaC service ([b84283a](https://github.com/InditexTech/kumoss/commit/b84283a7bca105471044271a64e16c6de268c215))
* carry the project identifier from the client to the IaC service ([76bbecd](https://github.com/InditexTech/kumoss/commit/76bbecd93e1aff8d770a6d1aefd77976b2ad68a4))
* **core:** add a script to move prompts from Phoenix to Langfuse ([ade4a35](https://github.com/InditexTech/kumoss/commit/ade4a352829daf9f150cb17287c440e3d7df3357))
* **core:** deny key removal and command execution, warn on credential outputs ([c08f4dd](https://github.com/InditexTech/kumoss/commit/c08f4dd578afb052cde1774a25476f59f1231288))
* **core:** enforce a Rego compliance policy with OPA ([074f6ac](https://github.com/InditexTech/kumoss/commit/074f6ac8f6eb85494c3c9991865f272e42cb3163))
* **core:** seed Rego policies and read which prompt version was used ([e2d3c14](https://github.com/InditexTech/kumoss/commit/e2d3c143f101cdd33ee7253697707a1a25d237d4))
* **core:** send traces and read prompts from Langfuse ([f7dd464](https://github.com/InditexTech/kumoss/commit/f7dd464f0a68afd4a76caa5686d9dab014c0fc19))
* enforce a Rego compliance policy with OPA and remove forbidden_actions ([ab04312](https://github.com/InditexTech/kumoss/commit/ab043120c7943330a8d655ca919ca7c1f596019e))
* enforce compliance policies scoped to the declared providers ([78c449c](https://github.com/InditexTech/kumoss/commit/78c449c63ad636af310c7ce798c8ca981da35124))
* **helm:** deploy Langfuse instead of Phoenix ([8f9238b](https://github.com/InditexTech/kumoss/commit/8f9238b3a8856a4b8b69ffd85d155b74c5efefee))
* narrow the LLM compliance audit to an intent check ([fcbe6ce](https://github.com/InditexTech/kumoss/commit/fcbe6ce7eefaef8a8b91d723729df3eee3778ddc))
* narrow the LLM compliance audit to an intent check ([877562e](https://github.com/InditexTech/kumoss/commit/877562ea7ffbb34ab4bce39a8af471c33f916046))
* promote develop to main (authz redesign, Langfuse, OPA compliance, contracts 2.0.0) ([6154152](https://github.com/InditexTech/kumoss/commit/6154152824d3385faaa6e41957bbdbcbc2dece21))
* promote develop to main (provider compliance policies, project identifier) ([3aecd55](https://github.com/InditexTech/kumoss/commit/3aecd551444c4913e5d32321c69128e5d260c8f8))
* provider compliance policies and policy-only enforcement ([c46d2f3](https://github.com/InditexTech/kumoss/commit/c46d2f385b0107c670cbaa3ee075ca997142a805))
* replace Phoenix with Langfuse for traces and prompts ([#552](https://github.com/InditexTech/kumoss/issues/552)) ([439b7f3](https://github.com/InditexTech/kumoss/commit/439b7f35855e2a53341df22638c3efdeb48c61de))
* **web:** link the admin panel to Langfuse ([579265f](https://github.com/InditexTech/kumoss/commit/579265f09490e916f08be9d7de95ffd632ee9f33))
* **web:** mark the compliance policy's findings ([378f264](https://github.com/InditexTech/kumoss/commit/378f26467ec8f98e46419a645edd3135bb1bbb1f))


### Bug Fixes

* **core:** accept only printable ASCII in project_identifier ([85ae24d](https://github.com/InditexTech/kumoss/commit/85ae24d7065ac251f8fcae75c456df52341f3b41))
* **core:** harden the Phoenix to Langfuse prompt migration ([2b09add](https://github.com/InditexTech/kumoss/commit/2b09add79cfd18fa0d6c72918a72d5e22ab7dad9))
* **core:** keep a prompt's type when the seeder updates it ([9425563](https://github.com/InditexTech/kumoss/commit/9425563226a2cb1edfaa1d47ce17ef65b3c07cc2))
* **core:** keep plan values out of compliance policy errors ([4779758](https://github.com/InditexTech/kumoss/commit/47797585f2c9d03f9a2619ca3441ca32ff05a42b))
* **core:** leave standalone deletions to the compliance policy ([71b67f5](https://github.com/InditexTech/kumoss/commit/71b67f542fd1758e3785a71d1f271d78b175c23e))
* **docs:** show Langfuse's {{variable}} placeholder literally ([4f5395e](https://github.com/InditexTech/kumoss/commit/4f5395eb8630cc086130c8f4d71edf86e1af0181))
* let Compose take a percent-encoded Langfuse database URL ([263e6b9](https://github.com/InditexTech/kumoss/commit/263e6b993f520be5f1d1e8b71492658b3694a8c5))


### Documentation

* describe Langfuse in place of Phoenix ([b797fd7](https://github.com/InditexTech/kumoss/commit/b797fd7aa3a148223a4d90b60bc28ae18c18a10d))
* document provider compliance policies and policy-only enforcement ([ccbb09a](https://github.com/InditexTech/kumoss/commit/ccbb09a2227caab1ecd735d619c01c59d1a4315e))
* document the OPA compliance policy and the removal of forbidden_actions ([db561d1](https://github.com/InditexTech/kumoss/commit/db561d1d8f15291460104eb5031c53755d423858))
* explain why a session locks and how an editor unlocks it ([f6780f7](https://github.com/InditexTech/kumoss/commit/f6780f72e8385c19cae30d821dec64a4e3dab6b5))
* link the root module manifest to the compliance policy ([120a7da](https://github.com/InditexTech/kumoss/commit/120a7da08b77b688eb985a07436bea46db04d0ce))
* move locked sessions into their own guide ([208b99e](https://github.com/InditexTech/kumoss/commit/208b99e3aa76f015b701f227ae4c8a6bd89764cc))
* restructure compliance and prompt docs and group the navigation ([44612bd](https://github.com/InditexTech/kumoss/commit/44612bd26a9b9d385e0721fc8eda81c2d59e506e))
* restructure Follow a session around an example report ([661f613](https://github.com/InditexTech/kumoss/commit/661f6135e704e6bc688bb063b873c14cfc6b15e7))
* restructure Follow a session around an example report ([174893d](https://github.com/InditexTech/kumoss/commit/174893d9f97b3a6a4ae2e0648ff3f5edae859765))
* **roadmap:** mark OPA and the Helm chart done ([8ae2720](https://github.com/InditexTech/kumoss/commit/8ae2720c5d03f72d5e9db6c724e2c3c93d09698b))
* show where compliance findings appear in a session ([097f555](https://github.com/InditexTech/kumoss/commit/097f555a20d620d947c77182dac8f9692ca002d7))
* use US English spelling throughout the site ([e58913c](https://github.com/InditexTech/kumoss/commit/e58913c22388d61a1ad769e2067860addbd679bb))

## [1.0.9](https://github.com/InditexTech/kumoss/compare/v1.0.8...v1.0.9) (2026-11-19)


### Bug Fixes

* **nginx:** bump the web image's nginx base to 1.31.9 to fix [CVE-2026-123007](https://www.cve.org/CVERecord?id=CVE-2026-123007) ("nginx2root"), an HTTP/2 flow-control integer underflow (CVSS 4.0 9.2) that can corrupt the heap and allow remote code execution in the worker process; it affects nginx 1.9.5 through 1.31.8 and is fixed in 1.31.9 (mainline) and 1.30.7 (stable). The base image is now pinned as `tag@digest` so the version is visible in reviews and scans ([#524](https://github.com/InditexTech/kumoss/issues/524)) ([5e095c9](https://github.com/InditexTech/kumoss/commit/5e095c90afe75ebfbf936345d07d8714f748eb9f))
* **deps:** bump dnspython to 2.9.2 in core, iac and notifications ([GHSA-vvf4-9x63-8xvv](https://osv.dev/GHSA-vvf4-9x63-8xvv)) ([#521](https://github.com/InditexTech/kumoss/issues/521)) ([b56e946](https://github.com/InditexTech/kumoss/commit/b56e9461db929094ff2e868cf073a430b9159a57))


### Documentation

* **quickstart:** point Kubernetes users to the published OCI Helm chart and the kind trial ([#497](https://github.com/InditexTech/kumoss/issues/497)) ([de614f6](https://github.com/InditexTech/kumoss/commit/de614f6c9371e2c196d040f491b5168b9b93db92))
* **readme:** add an OpenTofu compatibility badge ([#492](https://github.com/InditexTech/kumoss/issues/492)) ([0d9e2ae](https://github.com/InditexTech/kumoss/commit/0d9e2aecde23eb72a45f2e745f6ce227a22acba7))
* **readme:** clarify the Kumoss project description ([#498](https://github.com/InditexTech/kumoss/issues/498)) ([917648f](https://github.com/InditexTech/kumoss/commit/917648fa05be17512fc9c81e84fdc1ac3c81ccee))

## [1.0.8](https://github.com/InditexTech/kumoss/compare/v1.0.7...v1.0.8) (2026-11-05)


### Bug Fixes

* **config:** raise the default `llm.max_output_tokens` from 32000 to 64000 ([#467](https://github.com/InditexTech/kumoss/issues/467)) ([46c20f3](https://github.com/InditexTech/kumoss/commit/46c20f34f5983847d4745d41af6f81f30f965e29))
* **nginx:** revalidate index.html and return 404 for missing hashed assets instead of HTML ([#464](https://github.com/InditexTech/kumoss/issues/464)) ([e4a2fce](https://github.com/InditexTech/kumoss/commit/e4a2fceb76dd2addfefcb4fa8c6b21f1c922b0f6))
* **pr_service:** stop the PR service crashing on creation; `web_search` moves to the workspace tool registry ([#466](https://github.com/InditexTech/kumoss/issues/466)) ([611268a](https://github.com/InditexTech/kumoss/commit/611268a4dc5467ddd33b1bdfe5be6d5610c997b9))

## [1.0.7](https://github.com/InditexTech/kumoss/compare/v1.0.6...v1.0.7) (2026-11-04)


### Features

* **ci:** publish the SearXNG image to GHCR ([540120b](https://github.com/InditexTech/kumoss/commit/540120b25d969abc58b1a7db0ad8f3b240a05aa5))


### Bug Fixes

* **ci:** build searxng from its own context and resolve its image tag ([f5fd25c](https://github.com/InditexTech/kumoss/commit/f5fd25c4a74ffac9120489e2f1a28edd0adcdaf5))
* **searxng:** honour a supplied settings path and escape the secret ([e9ff814](https://github.com/InditexTech/kumoss/commit/e9ff814f73578d81ac1d6b5d217ac115026b4ec5))

## [1.0.6](https://github.com/InditexTech/kumoss/compare/v1.0.5...v1.0.6) (2026-11-03)


### Features

* **helm:** add caBundle to trust extra CA roots in every outbound pod ([d5280d3](https://github.com/InditexTech/kumoss/commit/d5280d3759467ce49048cef74304f726ca63c31d))
* **helm:** add kind-up.sh to bring the chart up on kind in one command ([15141ea](https://github.com/InditexTech/kumoss/commit/15141eafcde3cb9a8903ee2eaa491bf7b06475cf))
* **helm:** caBundle for all outbound pods, kind-up.sh, and OCI chart publishing ([605f4c3](https://github.com/InditexTech/kumoss/commit/605f4c33386160cc8c84484da37456446466dc1e))


### Bug Fixes

* **core:** trust every certificate in multi-certificate CA files ([636331d](https://github.com/InditexTech/kumoss/commit/636331d54956fc1ccac92f4fde47ac6676907574))
* **helm:** keep glued certificates in caBundle and set AWS_CA_BUNDLE ([6170f03](https://github.com/InditexTech/kumoss/commit/6170f03d476c1bb10a8fff16e829e438f4519369))
* **helm:** validate the chart before kind-up.sh touches the cluster ([81c49a8](https://github.com/InditexTech/kumoss/commit/81c49a8bf0c20a4b2400d06ae1faa4d746ee8c5b))


### Documentation

* **helm:** document caBundle, kind-up.sh and the OCI chart ([bcb0fcb](https://github.com/InditexTech/kumoss/commit/bcb0fcb34c5c22f2182aa40db865593871cbe34a))

## [1.0.5](https://github.com/InditexTech/kumoss/compare/v1.0.4...v1.0.5) (2026-11-02)


### Features

* **helm:** deploy Kumoss on Kubernetes with a Helm chart ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([df35e14](https://github.com/InditexTech/kumoss/commit/df35e14cacffb625b419b4d26270a6f3eeb04942))


### Bug Fixes

* **core:** answer `GET /healthz` so orchestrators can probe the core ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([3429bfe](https://github.com/InditexTech/kumoss/commit/3429bfe67768604f31d94aafb6a71ffe7171e261))


### Documentation

* add the Deploy with Helm guide for kind, AKS, EKS and GKE ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([df35e14](https://github.com/InditexTech/kumoss/commit/df35e14cacffb625b419b4d26270a6f3eeb04942))

## [1.0.4](https://github.com/InditexTech/kumoss/compare/v1.0.3...v1.0.4) (2026-11-02)


### Bug Fixes

* **deps:** bump graphql-core to 3.3.1 ([GHSA-mpqx-q82w-9x46](https://osv.dev/GHSA-mpqx-q82w-9x46)) ([b5e416a](https://github.com/InditexTech/kumoss/commit/b5e416afe558d8b0daf438fc3b9102e279c735dc))
* **deps:** bump pyasn1 to 0.6.5 in core and iac ([GHSA-2qm8-x737-gmw5](https://osv.dev/GHSA-2qm8-x737-gmw5), [GHSA-9m75-vc3g-4x39](https://osv.dev/GHSA-9m75-vc3g-4x39), [GHSA-fm9c-5rcf-2q5p](https://osv.dev/GHSA-fm9c-5rcf-2q5p), [GHSA-mm57-4v3p-rchx](https://osv.dev/GHSA-mm57-4v3p-rchx)) ([b5e416a](https://github.com/InditexTech/kumoss/commit/b5e416afe558d8b0daf438fc3b9102e279c735dc))
* **docs:** upgrade docouture to 1.3.2 so search links keep the site path ([34ad0a9](https://github.com/InditexTech/kumoss/commit/34ad0a90c9dc3dde1232937ac5384f042eaaf9d3))


### Documentation

* add README audience section and roadmap table ([a153a17](https://github.com/InditexTech/kumoss/commit/a153a173970ed530d98c01591d1c4dfb9d1a65d4))
* use the white README banner in every theme ([f63c4ef](https://github.com/InditexTech/kumoss/commit/f63c4efba6a164231699bb03349d64e60e32a0cb))

## [1.0.3](https://github.com/InditexTech/kumoss/compare/v1.0.2...v1.0.3) (2026-10-29)


### Bug Fixes

* **deps:** bump dnspython to 2.9.0 ([GHSA-45c3-73f7-pv4m](https://osv.dev/GHSA-45c3-73f7-pv4m)) ([db959e4](https://github.com/InditexTech/kumoss/commit/db959e4a869170ca3d340973a04c98b823f2cb93))


### Documentation

* add QuickStart section to README ([75ab278](https://github.com/InditexTech/kumoss/commit/75ab278fa17fbd499bfe0d83629504ff3c4d5e2c))
* add real-run demo video to README and docs site ([56f1e6d](https://github.com/InditexTech/kumoss/commit/56f1e6d7f90bb01e86b4bff0b87b61d3f95e3349))
* add roadmap section to README ([2482f02](https://github.com/InditexTech/kumoss/commit/2482f0213ac72f1927ba8bb5c65934111a890108))
* simplify README roadmap section ([087c43a](https://github.com/InditexTech/kumoss/commit/087c43a6e24f238337db09b328c69cb9137a4154))
* update real-run demo video ([ab32583](https://github.com/InditexTech/kumoss/commit/ab325830ce23e8220cae6358713687825e95ee68))
* update real-run demo video with sharper cloud console footage ([07fb52e](https://github.com/InditexTech/kumoss/commit/07fb52ea5ae0d2cc05d291632c856a5363d71efc))

## [1.0.2](https://github.com/InditexTech/kumoss/compare/v1.0.1...v1.0.2) (2026-10-26)


### Bug Fixes

* **iac:** increase iac plan target max limit to 4096 ([9ce8752](https://github.com/InditexTech/kumoss/commit/9ce8752e0777e753a9d0db1c932c8b6f1732eca7))
* **import:** build import IDs in the provider's documented format ([769eafd](https://github.com/InditexTech/kumoss/commit/769eafd5b07bc96f8d521f75e59272e80f4a9b1c))
* **import:** remove unused `status` tool field - steer the model to use web_search - listed_id always present ([54ad0a5](https://github.com/InditexTech/kumoss/commit/54ad0a52b21b1c0b23ad718d2110b2df4df7caf8))
* **tests:** update import tests ([5f34aa3](https://github.com/InditexTech/kumoss/commit/5f34aa324e607821b0fb0d5bea1e6a5b0527cb52))

## [1.0.1](https://github.com/InditexTech/kumoss/compare/v1.0.0...v1.0.1) (2026-10-23)


### Bug Fixes

* **ci:** pass the host-certs build context when publishing images ([afbc217](https://github.com/InditexTech/kumoss/commit/afbc21711c0906b74c1f3f6305ae7dd81d6cba64))
* **deps:** Bump dompurify to 3.4.17 and graphql-core to 3.2.13 ([5f5ec61](https://github.com/InditexTech/kumoss/commit/5f5ec6117951402ddafd5f8c7816404168001ef7))
* Publish the core image and bump OSV-flagged dependencies ([978ad13](https://github.com/InditexTech/kumoss/commit/978ad1329b1d254fdb75170262e729d862b02739))

## Changelog
