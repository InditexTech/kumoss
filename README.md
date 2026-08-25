<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

<!-- Add relevant badges here -->
![GitHub License](https://img.shields.io/github/license/InditexTech/base-archetype)

# base-archetype

Short description of what this project does and why it exists.

> One or two sentences that explain its purpose in a clear, accessible way.

<!-- Add video/image/demo here -->

## LiteLLM Models and Params Reference

### 1. Major Cloud Platforms (Hyperscalers)


| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Azure AI Foundry** (Claude, Llama, etc.) | `azure_ai/<model-name>` | `AZURE_AI_API_KEY`<br>`AZURE_AI_API_BASE` | `api_key`<br>`api_base` | `https://<resource>.services.ai.azure.com/anthropic` (or `/models`) |
| **Azure OpenAI** | `azure/<deployment-name>` | `AZURE_API_KEY`<br>`AZURE_API_BASE`<br>`AZURE_API_VERSION` | `api_key`<br>`api_base`<br>`api_version` | `https://<resource>.openai.azure.com` |
| **Google Vertex AI** | `vertex_ai/<model-name>` | `VERTEXAI_PROJECT`<br>`VERTEXAI_LOCATION`<br>`GOOGLE_APPLICATION_CREDENTIALS` | `vertex_project`<br>`vertex_location`<br>`vertex_credentials` | Auth via GCP Service Account JSON or ADC. |
| **Google AI Studio (Gemini API)** | `gemini/<model-name>` | `GEMINI_API_KEY` | `api_key` | Direct Google AI Studio API key. |
| **AWS Bedrock** | `bedrock/<model-id>` | `AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY`<br>`AWS_REGION_NAME` | `aws_access_key_id`<br>`aws_secret_access_key`<br>`aws_region_name` | Model IDs like `anthropic.claude-3-5-sonnet-20241022-v2:0`. |
| **AWS SageMaker** | `sagemaker/<endpoint-name>` | `AWS_ACCESS_KEY_ID`<br>`AWS_SECRET_ACCESS_KEY`<br>`AWS_REGION_NAME` | `aws_access_key_id`<br>`aws_secret_access_key`<br>`aws_region_name` | Targeted SageMaker deployed endpoint. |
| **Cloudflare Workers AI** | `cloudflare/<model-name>` | `CLOUDFLARE_API_KEY`<br>`CLOUDFLARE_ACCOUNT_ID` | `api_key`<br>`api_base` | Direct access to serverless models on Cloudflare. |

---

### 2. Frontier Model Labs (Direct API)

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Anthropic** | `anthropic/<model-name>` | `ANTHROPIC_API_KEY` | `api_key` | e.g., `anthropic/claude-3-5-sonnet-20241022` |
| **OpenAI** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | `api_base` defaults to `https://api.openai.com/v1`. |
| **xAI (Grok)** | `xai/<model-name>` | `XAI_API_KEY` | `api_key` | e.g., `xai/grok-beta` |
| **Mistral AI** | `mistral/<model-name>` | `MISTRAL_API_KEY` | `api_key` | e.g., `mistral/mistral-large-latest` |
| **Cohere** | `cohere/<model-name>` or `cohere_chat/<model-name>` | `COHERE_API_KEY` | `api_key` | e.g., `cohere/command-r-plus` |

---

### 3. Hosted Inference & Fast Token Providers

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Groq** | `groq/<model-name>` | `GROQ_API_KEY` | `api_key` | e.g., `groq/llama-3.3-70b-versatile` |
| **DeepSeek** | `deepseek/<model-name>` | `DEEPSEEK_API_KEY` | `api_key` | e.g., `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` |
| **Together AI** | `together_ai/<model-name>` | `TOGETHERAI_API_KEY` | `api_key` | e.g., `together_ai/meta-llama/Llama-3.3-70B-Instruct-Turbo` |
| **Fireworks AI** | `fireworks_ai/<model-name>` | `FIREWORKS_AI_API_KEY` | `api_key` | e.g., `fireworks_ai/accounts/fireworks/models/llama-v3p3-70b-instruct` |
| **OpenRouter** | `openrouter/<model-name>` | `OPENROUTER_API_KEY` | `api_key` | e.g., `openrouter/anthropic/claude-3.5-sonnet` |
| **Perplexity AI** | `perplexity/<model-name>` | `PERPLEXITYAI_API_KEY` | `api_key` | e.g., `perplexity/sonar-pro` |
| **Cerebras** | `cerebras/<model-name>` | `CEREBRAS_API_KEY` | `api_key` | e.g., `cerebras/llama3.3-70b` |
| **SambaNova** | `sambanova/<model-name>` | `SAMBANOVA_API_KEY` | `api_key` | e.g., `sambanova/Meta-Llama-3.3-70B-Instruct` |
| **DeepInfra** | `deepinfra/<model-name>` | `DEEPINFRA_API_KEY` | `api_key` | e.g., `deepinfra/meta-llama/Meta-Llama-3.1-70B-Instruct` |
| **Anyscale** | `anyscale/<model-name>` | `ANYSCALE_API_KEY` | `api_key` | e.g., `anyscale/meta-llama/Llama-3-70b-chat-hf` |
| **Replicate** | `replicate/<model-name>` | `REPLICATE_API_KEY` (or `REPLICATE_API_TOKEN`) | `api_key` | e.g., `replicate/meta/meta-llama-3-70b-instruct` |
| **Voyage AI** (Embeddings) | `voyage/<model-name>` | `VOYAGE_API_KEY` | `api_key` | e.g., `voyage/voyage-3` |
| **AI21** | `ai21/<model-name>` | `AI21_API_KEY` | `api_key` | e.g., `ai21/jamba-1.5-large` |


---

### 4. Enterprise Data Platforms


| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Databricks** | `databricks/<endpoint-name>` | `DATABRICKS_API_KEY`<br>`DATABRICKS_API_BASE` | `api_key`<br>`api_base` | `api_base` format: `https://<workspace>.cloud.databricks.com/serving-endpoints` |
| **IBM WatsonX** | `watsonx/<model-id>` | `WATSONX_APIKEY`<br>`WATSONX_URL`<br>`WATSONX_PROJECT_ID` | `api_key`<br>`api_base`<br>`watsonx_project_id` | `api_base` is the regional URL (e.g., `https://us-south.ml.cloud.ibm.com`). |
| **Snowflake Cortex** | `snowflake/<model-name>` | `SNOWFLAKE_ACCOUNT_ID`<br>`SNOWFLAKE_USER`<br>`SNOWFLAKE_PASSWORD` | `snowflake_account_id`<br>`snowflake_user`<br>`snowflake_password` | Supports Llama, Mistral hosted in Snowflake. |

---


### 5. Self-Hosted, Local, and OpenAI-Compatible Engines

| Provider | Model String Format (`model:`) | Default LiteLLM Env Vars | Standard `litellm_params` Keys | Base URL / Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Ollama** | `ollama/<model-name>` | `OLLAMA_API_BASE` | `api_base` | Default base: `http://localhost:11434`. (No API key needed). |
| **vLLM** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | Point `api_base` to `http://<host>:<port>/v1`. Use dummy `api_key: "none"`. |
| **TGI (HuggingFace Text Gen)** | `huggingface/<model-name>` or `tgi/<endpoint>` | `HUGGINGFACE_API_KEY` | `api_key`<br>`api_base` | Endpoint URL from HF Dedicated Endpoints or local TGI. |
| **Hugging Face Serverless** | `huggingface/<repo/model>` | `HUGGINGFACE_API_KEY` (or `HF_TOKEN`) | `api_key` | Standard Hugging Face inference tokens. |
| **Generic OpenAI-Compatible** | `openai/<model-name>` | `OPENAI_API_KEY`<br>`OPENAI_API_BASE` | `api_key`<br>`api_base` | Works with LocalAI, LM Studio, FastChat, TabbyAPI, etc. |

## Features

- 🔧 Key functionality or tools
- 📦 What problem it solves
- 🚀 Target audience or use case

## Getting Started

### Installation

Explain how to install or run the project.

```bash
# Example for a CLI tool
npm install -g @inditextech/your-tool
```

### Usage

Show basic usage or link to examples.

```bash
your-tool init
```

## Contributing

We welcome contributions!

Please read our [CONTRIBUTING.md](./CONTRIBUTING.md) and follow the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for planned features and development goals.

<!-- or -->

## Acknowledgments

<!-- Mention any projects used as inspiration, key dependencies... -->

## License

This project is licensed under the [Apache-2.0 License](./LICENSE).

© 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
