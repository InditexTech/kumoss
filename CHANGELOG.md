# Changelog

## [1.0.5](https://github.com/InditexTech/kumoss/compare/v1.0.4...v1.0.5) (2026-11-02)


### Features

* **helm:** add Kubernetes Helm chart ([df35e14](https://github.com/InditexTech/kumoss/commit/df35e14cacffb625b419b4d26270a6f3eeb04942))
* **helm:** add Kubernetes Helm chart and core /healthz ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([df851d2](https://github.com/InditexTech/kumoss/commit/df851d20bfb9279c5c1d7918c57bf0c937d5371d))


### Bug Fixes

* **core:** add /healthz liveness endpoint ([3429bfe](https://github.com/InditexTech/kumoss/commit/3429bfe67768604f31d94aafb6a71ffe7171e261))
* **helm:** address review findings ([0227ea3](https://github.com/InditexTech/kumoss/commit/0227ea3c65dfe26aac690ca07a452868afcfc4ed))

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
