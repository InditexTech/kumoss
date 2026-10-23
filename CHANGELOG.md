# Changelog

## [1.1.0](https://github.com/InditexTech/kumoss/compare/v1.0.0...v1.1.0) (2026-10-23)


### Features

* add VMware vSphere provider ([316df4f](https://github.com/InditexTech/kumoss/commit/316df4f5e26fa828acf40ad4ab095ebbd1872ad5))
* align cloud seeds with best practices and enforce AWS/OCI scope ([#387](https://github.com/InditexTech/kumoss/issues/387)) ([534aac3](https://github.com/InditexTech/kumoss/commit/534aac38629fac0aa704a40892dabec668edc399))
* **config:** route llm roles through model_list aliases ([e51cfab](https://github.com/InditexTech/kumoss/commit/e51cfabb19f68c39ce22c2e83e06aa33d3a966a1))
* **core:** report the release version in the OpenAPI document by default ([f65c092](https://github.com/InditexTech/kumoss/commit/f65c09272f498835201f02377b45947a8793dfc4))
* **tools:** route agent web searches through a self-hosted SearXNG engine ([1567082](https://github.com/InditexTech/kumoss/commit/1567082945e0ba4ea12fffc706c60af639030295))
* **uv:** Added trafilatura package for web search service ([d0121aa](https://github.com/InditexTech/kumoss/commit/d0121aa96cc3bff7f9ec86adbd71f53ebc9f2002))
* **web_search:** Read result pages instead of LLM-native search ([9ae0a0f](https://github.com/InditexTech/kumoss/commit/9ae0a0f890bd056e8595a920e3dd06b77c512ce8))
* **web_search:** Remove the _search_dead_end counter as is an edge_case scenario and is currently managed by re-wording the search query by the model ([5340a79](https://github.com/InditexTech/kumoss/commit/5340a7967f46555decf3a22be7009a095deaa8c6))
* **web_search:** Render result pages in headless Chromium ([e99ed95](https://github.com/InditexTech/kumoss/commit/e99ed9567d5ec75c81fdd6036d2d48baccda4b54))
* **web_search:** Summarization is now enforced/the by default behaviour. Now, every web search summarize its content before handing it over to the llm to rank and filter the content. ([6a67e5c](https://github.com/InditexTech/kumoss/commit/6a67e5caaee3dc324805bc27fdb4dc8e66a0b935))
* **web_search:** Summarize and rank results before the agent reads them ([517c819](https://github.com/InditexTech/kumoss/commit/517c819890e1959be63092b0fb906dc00961b75c))


### Bug Fixes

* **aiohttp:** Upgrade to version 3.14.5 to fix security issue ([3d38fdb](https://github.com/InditexTech/kumoss/commit/3d38fdb22028bdec68d017183ca940ee2defccec))
* **compose:** Move corporate proxy certs out of the base stack ([ad4e9b9](https://github.com/InditexTech/kumoss/commit/ad4e9b95ae2b7b3dc2753012fca532634c61623c))
* **core:** detect create-before-destroy replacements in drift ([7e14e11](https://github.com/InditexTech/kumoss/commit/7e14e1138d75a921de83c3099be5f2973392b23b))
* **core:** detect create-before-destroy replacements in drift ([#319](https://github.com/InditexTech/kumoss/issues/319)) ([fa21183](https://github.com/InditexTech/kumoss/commit/fa21183c0c7f883cbc0f21145b5c6ead882b1708))
* **core:** Fix comment reviews ([9877f2c](https://github.com/InditexTech/kumoss/commit/9877f2cb6c95b74fc0570c64bdb91e7966408bbb))
* **core:** Return config.yaml for llm to default ([111c824](https://github.com/InditexTech/kumoss/commit/111c8248691fa3b2b26f2e57254da6468f996d93))
* **deps:** bump mako, multidict and werkzeug to clear OSV advisories ([#303](https://github.com/InditexTech/kumoss/issues/303)) ([91da83e](https://github.com/InditexTech/kumoss/commit/91da83ece6d176d92e01cce799ae7ad931f489e7))
* **deps:** sync uv.lock ([00ba01d](https://github.com/InditexTech/kumoss/commit/00ba01d8adbc0b94d4ede72464f3912ab0dabde8))
* **docs:** Correct escape character in web_search.endpoint URL ([73ee70e](https://github.com/InditexTech/kumoss/commit/73ee70e85c37ef460ba6ecc57af311af8e6e800d))
* **docs:** Fix doc reference to a variable ([a3394e6](https://github.com/InditexTech/kumoss/commit/a3394e601de1b33ea79f425019adf19a226b4684))
* **docs:** point the docouture changelog step at the root CHANGELOG.md ([c42abc2](https://github.com/InditexTech/kumoss/commit/c42abc2ceb367f7a3bdf274c480cebc9e3c087b6))
* **iac:** address review feedback on cloud provider resource filters ([2d76c3d](https://github.com/InditexTech/kumoss/commit/2d76c3d2d98cc2e9d5207c677e437cbe09401759))
* **iac:** filter auto-generated cloud provider resources in scope discovery ([#305](https://github.com/InditexTech/kumoss/issues/305), [#306](https://github.com/InditexTech/kumoss/issues/306)) ([f51c3d1](https://github.com/InditexTech/kumoss/commit/f51c3d1ae7d3843b26ce3c8ced9f21dcf2852832))
* **iac:** resolve CodeQL incomplete URL substring sanitization in GCP discovery ([8b262ab](https://github.com/InditexTech/kumoss/commit/8b262ab30f4065d538b31c46925e4ece72638c85))
* Pin docker version of SearXNG ([7506afc](https://github.com/InditexTech/kumoss/commit/7506afc53ec3afbaaf821ca87e7097a2e873d18b))
* **release:** bump the authz conformance uv.lock with the other version files ([e2d2806](https://github.com/InditexTech/kumoss/commit/e2d2806884a67a3c08e8c98c6294ccdd068a5c44))
* remove the unused authz and mapping reference services ([c314937](https://github.com/InditexTech/kumoss/commit/c3149371bb4a870ecec03a08627b7454e70f75c1))
* remove the unused authz and mapping reference services ([#362](https://github.com/InditexTech/kumoss/issues/362)) ([3ce61db](https://github.com/InditexTech/kumoss/commit/3ce61dbdd4acd61f6a80014b001af462b391f7c2))
* **REUSE:** Added REUSE requirement ([c6d042b](https://github.com/InditexTech/kumoss/commit/c6d042b287134562c7f4b6344b525d7787faeaaa))
* **search_service:** Moved search service exceptions to infrastructure/exceptions ([e41a611](https://github.com/InditexTech/kumoss/commit/e41a611492268c93fea9d69eba93191d66c3fb20))
* **searxng:** Keep only the engines a general query needs ([94b9e9f](https://github.com/InditexTech/kumoss/commit/94b9e9f2fc5599cb899ad6d951ee5f37382b0cec))
* **security:** Upgrade the certifi packages ([9049307](https://github.com/InditexTech/kumoss/commit/9049307b00f5de802aed9d953c901c0be38425ae))
* **test:** Fix import starting with ([0755285](https://github.com/InditexTech/kumoss/commit/075528564c1e2d322dd27a65af5474eb7c602d4e))
* **vmware:** address review feedback and merge main ([db0ec19](https://github.com/InditexTech/kumoss/commit/db0ec19ea8f483a7a81730345677162bc48981da))


### Documentation

* add a public roadmap page ([f65f260](https://github.com/InditexTech/kumoss/commit/f65f260dd23c6cc572a7d751260bc8bf6a106a18))
* add a public roadmap page ([06f1567](https://github.com/InditexTech/kumoss/commit/06f156715e40cb41661f15b37271b6f87db3bb17))
* add cost management initiatives to the roadmap ([ac4a416](https://github.com/InditexTech/kumoss/commit/ac4a416b8e2f5b2179e11f896f02b9da359347b1))
* add cost management initiatives to the roadmap ([4563438](https://github.com/InditexTech/kumoss/commit/45634387cefff64c5a0eede3a23ca463bcc83392))
* add how-it-works and bring-your-own notifications to the README ([18cd92d](https://github.com/InditexTech/kumoss/commit/18cd92dab58a338f65cabd5b79554a2cd9ed4cf4))
* add how-it-works and bring-your-own notifications to the README ([005e2d2](https://github.com/InditexTech/kumoss/commit/005e2d2d13dd3f552f6af6c34611f250b0ba0cf9))
* add key capabilities to the README, home, and About pages ([e38ee0f](https://github.com/InditexTech/kumoss/commit/e38ee0ff5968f209754d1fea688514ea8b59d73c))
* add key capabilities to the README, home, and About pages ([c24d64e](https://github.com/InditexTech/kumoss/commit/c24d64e0310f957fc453cdae4b2eba6097e62e01))
* add the Kernel Panic talk slides ([#314](https://github.com/InditexTech/kumoss/issues/314)) ([852a3d1](https://github.com/InditexTech/kumoss/commit/852a3d18d66d2d418c305c33715dbbd211697174))
* add the multicloud governance overview to the roadmap ([a3c367f](https://github.com/InditexTech/kumoss/commit/a3c367f4982149d5bbd48cbd7e842d5163d9f909))
* add the multicloud governance overview to the roadmap ([b28241f](https://github.com/InditexTech/kumoss/commit/b28241f75bc3e696877f9027f02d96dff9557fbd))
* align release guidance with published releases ([2feab24](https://github.com/InditexTech/kumoss/commit/2feab24d9aef3690495080bb5a4dfb647bf5966d))
* **compose:** Add a tracked local-override template for TLS proxies ([04fbfe0](https://github.com/InditexTech/kumoss/commit/04fbfe0ad6a50ab0fdc51e84419de749cbd6a96d))
* correct core startup dependency notes ([90af1e3](https://github.com/InditexTech/kumoss/commit/90af1e3bb7614c9bf5c3f6b2dbfa14b394ca4f48))
* document the published GHCR core image ([86a5915](https://github.com/InditexTech/kumoss/commit/86a5915ab830b7d11a07a653bd9963d7813c0e55))
* fix OpenAPI capitalization in the hero video description ([97fc3c3](https://github.com/InditexTech/kumoss/commit/97fc3c30112bf057eef582f759ae2df1337aa0e4))
* **readme:** Update the README to add the search engine ([d81e3e6](https://github.com/InditexTech/kumoss/commit/d81e3e69b18c2263dbd8b31f693fcfc7725d4051))
* replace the overview video in the README and the docs home page ([3ea5237](https://github.com/InditexTech/kumoss/commit/3ea52374d95f92e731519d19b7b685b8244af3fd))
* replace the overview video in the README and the docs home page ([#315](https://github.com/InditexTech/kumoss/issues/315)) ([dfec68d](https://github.com/InditexTech/kumoss/commit/dfec68dec7d078a4fe0821c4e994af1864c27d19))
* replace the overview video music with an upbeat original score ([061fe60](https://github.com/InditexTech/kumoss/commit/061fe609d383bad2dbd90cb2491b1487451d0fd1))
* replace the overview video music with an upbeat original score ([75f6255](https://github.com/InditexTech/kumoss/commit/75f6255fe5ef406277bbc3d04b4f9d0974fe00d1))
* **roadmap:** add bulk operations and multiproject requests ([3832dc4](https://github.com/InditexTech/kumoss/commit/3832dc4ffbad33e4627330be31b968c63f7791f4))
* **roadmap:** add bulk operations and multiproject requests ([548b939](https://github.com/InditexTech/kumoss/commit/548b93952e215097d5e69543104fbe60b78dfac3))
* state that the command-execution ban on generated HCL is prompt-only ([76118df](https://github.com/InditexTech/kumoss/commit/76118dfd25bff792c4590b471edcc4b41397b287))
* **tools:** document web_search config and the searxng sidecar ([d0374de](https://github.com/InditexTech/kumoss/commit/d0374dedf9d16554fd9fc72551c17c315882c613))

## Changelog
