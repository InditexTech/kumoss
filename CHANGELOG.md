# Changelog

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
