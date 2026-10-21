# Changelog

## [1.3.0](https://github.com/InditexTech/kumoss/compare/v1.2.0...v1.3.0) (2026-10-21)


### Features

* **config:** route LLM roles through `llm.model_list` LiteLLM aliases, so a role can target a self-hosted OpenAI-compatible endpoint (e.g. `hosted_vllm/…` with its own `api_base` and key) while the other stays hosted ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([e51cfab](https://github.com/InditexTech/kumoss/commit/e51cfabb19f68c39ce22c2e83e06aa33d3a966a1))
* **tools:** route agent web searches through a configurable search backend (new `web_search.*` config block, validated at boot) instead of LLM-native search, which self-hosted models lack; an empty provider disables the tool ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([1567082](https://github.com/InditexTech/kumoss/commit/1567082945e0ba4ea12fffc706c60af639030295), [9ae0a0f](https://github.com/InditexTech/kumoss/commit/9ae0a0f890bd056e8595a920e3dd06b77c512ce8))
* **searxng:** add a bundled self-hosted SearXNG sidecar (`services/searxng/`, port 8888) wired into Docker Compose ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([1567082](https://github.com/InditexTech/kumoss/commit/1567082945e0ba4ea12fffc706c60af639030295))
* **web_search:** read full result pages rendered in headless Chromium (Playwright + trafilatura) instead of engine snippets, falling back to the snippet when a page cannot be read ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([e99ed95](https://github.com/InditexTech/kumoss/commit/e99ed9567d5ec75c81fdd6036d2d48baccda4b54))
* **web_search:** summarize each page and rank them with the small model before the agent reads them, bounding context to the top `summarize_top` summaries; summarization is on by default ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([517c819](https://github.com/InditexTech/kumoss/commit/517c819890e1959be63092b0fb906dc00961b75c), [6a67e5c](https://github.com/InditexTech/kumoss/commit/6a67e5caaee3dc324805bc27fdb4dc8e66a0b935), [5340a79](https://github.com/InditexTech/kumoss/commit/5340a7967f46555decf3a22be7009a095deaa8c6))


### Bug Fixes

* **compose:** move corporate proxy certificate handling out of the base stack into an opt-in local override ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([ad4e9b9](https://github.com/InditexTech/kumoss/commit/ad4e9b95ae2b7b3dc2753012fca532634c61623c))
* **searxng:** keep only the engines a general query needs (bing, duckduckgo, brave) to avoid upstream rate-limiting ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([94b9e9f](https://github.com/InditexTech/kumoss/commit/94b9e9f2fc5599cb899ad6d951ee5f37382b0cec))
* **security:** upgrade aiohttp to 3.14.5 and certifi to address security issues ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([3d38fdb](https://github.com/InditexTech/kumoss/commit/3d38fdb22028bdec68d017183ca940ee2defccec), [9049307](https://github.com/InditexTech/kumoss/commit/9049307b00f5de802aed9d953c901c0be38425ae))


### Documentation

* document the `web_search` configuration, the SearXNG sidecar, `llm.model_list` and a tracked `docker-compose.override.example.yml` for TLS-inspecting proxies ([#345](https://github.com/InditexTech/kumoss/issues/345)) ([d0374de](https://github.com/InditexTech/kumoss/commit/d0374dedf9d16554fd9fc72551c17c315882c613), [04fbfe0](https://github.com/InditexTech/kumoss/commit/04fbfe0ad6a50ab0fdc51e84419de749cbd6a96d))

## [1.2.0](https://github.com/InditexTech/kumoss/compare/v1.1.0...v1.2.0) (2026-10-20)


### Features

* align cloud seeds with best practices and enforce AWS/OCI scope ([#387](https://github.com/InditexTech/kumoss/issues/387)) ([534aac3](https://github.com/InditexTech/kumoss/commit/534aac38629fac0aa704a40892dabec668edc399))

## [1.1.0](https://github.com/InditexTech/kumoss/compare/v1.0.9...v1.1.0) (2026-10-16)


### Features

* add VMware vSphere provider ([316df4f](https://github.com/InditexTech/kumoss/commit/316df4f5e26fa828acf40ad4ab095ebbd1872ad5))


### Bug Fixes

* **vmware:** address review feedback and merge main ([db0ec19](https://github.com/InditexTech/kumoss/commit/db0ec19ea8f483a7a81730345677162bc48981da))

## [1.0.9](https://github.com/InditexTech/kumoss/compare/v1.0.8...v1.0.9) (2026-10-15)


### Bug Fixes

* **iac:** resolve CodeQL incomplete URL substring sanitization in GCP discovery ([8b262ab](https://github.com/InditexTech/kumoss/commit/8b262ab30f4065d538b31c46925e4ece72638c85))

## [1.0.8](https://github.com/InditexTech/kumoss/compare/v1.0.7...v1.0.8) (2026-10-15)


### Bug Fixes

* remove the unused authz and mapping reference services ([c314937](https://github.com/InditexTech/kumoss/commit/c3149371bb4a870ecec03a08627b7454e70f75c1))
* remove the unused authz and mapping reference services ([#362](https://github.com/InditexTech/kumoss/issues/362)) ([3ce61db](https://github.com/InditexTech/kumoss/commit/3ce61dbdd4acd61f6a80014b001af462b391f7c2))

## [1.0.7](https://github.com/InditexTech/kumoss/compare/v1.0.6...v1.0.7) (2026-10-15)


### Documentation

* add cost management initiatives to the roadmap ([ac4a416](https://github.com/InditexTech/kumoss/commit/ac4a416b8e2f5b2179e11f896f02b9da359347b1))
* replace the overview video music with an upbeat original score ([061fe60](https://github.com/InditexTech/kumoss/commit/061fe609d383bad2dbd90cb2491b1487451d0fd1))
* replace the overview video music with an upbeat original score ([75f6255](https://github.com/InditexTech/kumoss/commit/75f6255fe5ef406277bbc3d04b4f9d0974fe00d1))
* **roadmap:** add bulk operations and multiproject requests ([3832dc4](https://github.com/InditexTech/kumoss/commit/3832dc4ffbad33e4627330be31b968c63f7791f4))
* **roadmap:** add bulk operations and multiproject requests ([548b939](https://github.com/InditexTech/kumoss/commit/548b93952e215097d5e69543104fbe60b78dfac3))

## [1.0.6](https://github.com/InditexTech/kumoss/compare/v1.0.5...v1.0.6) (2026-10-14)


### Documentation

* add the multicloud governance overview to the roadmap ([a3c367f](https://github.com/InditexTech/kumoss/commit/a3c367f4982149d5bbd48cbd7e842d5163d9f909))
* add the multicloud governance overview to the roadmap ([b28241f](https://github.com/InditexTech/kumoss/commit/b28241f75bc3e696877f9027f02d96dff9557fbd))

## [1.0.5](https://github.com/InditexTech/kumoss/compare/v1.0.4...v1.0.5) (2026-10-14)


### Documentation

* add a public roadmap page ([f65f260](https://github.com/InditexTech/kumoss/commit/f65f260dd23c6cc572a7d751260bc8bf6a106a18))
* add a public roadmap page ([06f1567](https://github.com/InditexTech/kumoss/commit/06f156715e40cb41661f15b37271b6f87db3bb17))

## [1.0.4](https://github.com/InditexTech/kumoss/compare/v1.0.3...v1.0.4) (2026-10-14)


### Documentation

* document the published GHCR core image ([86a5915](https://github.com/InditexTech/kumoss/commit/86a5915ab830b7d11a07a653bd9963d7813c0e55))

## [1.0.3](https://github.com/InditexTech/kumoss/compare/v1.0.2...v1.0.3) (2026-10-13)


### Bug Fixes

* **core:** detect create-before-destroy replacements in drift ([7e14e11](https://github.com/InditexTech/kumoss/commit/7e14e1138d75a921de83c3099be5f2973392b23b))
* **core:** detect create-before-destroy replacements in drift ([#319](https://github.com/InditexTech/kumoss/issues/319)) ([fa21183](https://github.com/InditexTech/kumoss/commit/fa21183c0c7f883cbc0f21145b5c6ead882b1708))


### Documentation

* replace the overview video in the README and the docs home page ([#315](https://github.com/InditexTech/kumoss/issues/315)) ([dfec68d](https://github.com/InditexTech/kumoss/commit/dfec68dec7d078a4fe0821c4e994af1864c27d19))

## [1.0.2](https://github.com/InditexTech/kumoss/compare/v1.0.1...v1.0.2) (2026-10-08)


### Documentation

* add the Kernel Panic talk slides ([#314](https://github.com/InditexTech/kumoss/issues/314)) ([852a3d1](https://github.com/InditexTech/kumoss/commit/852a3d18d66d2d418c305c33715dbbd211697174))

## [1.0.1](https://github.com/InditexTech/kumoss/compare/v1.0.0...v1.0.1) (2026-10-08)


### Documentation

* add how-it-works and bring-your-own notifications to the README ([18cd92d](https://github.com/InditexTech/kumoss/commit/18cd92dab58a338f65cabd5b79554a2cd9ed4cf4))
* add how-it-works and bring-your-own notifications to the README ([005e2d2](https://github.com/InditexTech/kumoss/commit/005e2d2d13dd3f552f6af6c34611f250b0ba0cf9))
* add key capabilities to the README, home, and About pages ([e38ee0f](https://github.com/InditexTech/kumoss/commit/e38ee0ff5968f209754d1fea688514ea8b59d73c))
* add key capabilities to the README, home, and About pages ([c24d64e](https://github.com/InditexTech/kumoss/commit/c24d64e0310f957fc453cdae4b2eba6097e62e01))

## [1.0.0](https://github.com/InditexTech/kumoss/compare/v0.1.0...v1.0.0) (2026-10-06)


### Features

* **core:** report the release version in the OpenAPI document by default ([f65c092](https://github.com/InditexTech/kumoss/commit/f65c09272f498835201f02377b45947a8793dfc4))


### Bug Fixes

* **deps:** bump mako, multidict and werkzeug to clear OSV advisories ([#303](https://github.com/InditexTech/kumoss/issues/303)) ([91da83e](https://github.com/InditexTech/kumoss/commit/91da83ece6d176d92e01cce799ae7ad931f489e7))
* **docs:** point the docouture changelog step at the root CHANGELOG.md ([c42abc2](https://github.com/InditexTech/kumoss/commit/c42abc2ceb367f7a3bdf274c480cebc9e3c087b6))
* **release:** bump the authz conformance uv.lock with the other version files ([e2d2806](https://github.com/InditexTech/kumoss/commit/e2d2806884a67a3c08e8c98c6294ccdd068a5c44))
