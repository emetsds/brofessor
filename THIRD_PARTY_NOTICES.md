# Third-party components

Document navigation and Ollama inference use `pydantic-ai-slim[openai]==2.66.0` and its locked dependencies,
installed unmodified from upstream packages. Pydantic AI Slim, Pydantic Graph,
genai-prices, logfire-api, and truststore use MIT licenses; griffelib uses ISC,
and httpx2/httpcore2 use BSD-3-Clause. Their distributions retain their notices.
The OpenAI extra supplies `openai==3.46.0` (Apache-2.0), `tiktoken==0.14.0`
(MIT), and `jiter==0.19.0` (MIT), installed unmodified with their distribution
notices. The SDK connects only to the explicitly selected Ollama server;
OpenAI/Codex OAuth providers and the separate alpha `pydantic-ai-harness` are not used.
No upstream source is vendored into brofessor.

PDF output embeds unmodified DejaVu Sans 2.37 from its
[official release](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37).
The fonts use the Bitstream Vera/DejaVu/Arev terms, separate from brofessor's MIT
license. [Complete font license](LICENSES/DejaVu.txt),
[provenance and hashes](src/brofessor/infrastructure/formats/fonts/README.md).

PDF processing uses pinned PyPI releases `pypdfium2==5.14.0` (BSD-3-Clause /
Apache-2.0 helpers; PDFium and its dependencies retain their bundled licenses)
and `reportlab==5.1.0` (BSD). The pypdfium2 wheel includes the full
`BUILD_LICENSES` notices for PDFium, FreeType, ICU, libjpeg-turbo and its other
native dependencies. They are installed as upstream packages; their native
libraries are not copied into this repository. BabelDOC is not a dependency.

PDF word wrapping also uses pinned `pyphen==0.18.1`, installed unmodified from
[its release](https://github.com/Kozea/Pyphen/releases/tag/0.18.1).
For the Pyphen code we select its MPL-1.1 option from the upstream
GPL-2.0+/LGPL-2.1+/MPL-1.1 tri-license; its wheel supplies the license texts.
The English (US) dictionary has its own BSD-style notice in the package.
The Russian dictionary is byte-identical to LibreOffice's `ru_RU/hyph_ru_RU.dic`
(SHA-256 `e9a6ae92765fc7e63d879f2ccf3f50f2b95bc8ed7618a6f31c34ce7d39844c83`).
Its [Alexander I. Lebedev copyright and redistribution notice](LICENSES/Russian-hyphenation.txt)
is retained here because Pyphen's dictionary-copy script omits that README.
No dictionary or Pyphen source is modified or vendored into brofessor.

The default speech profile downloads Qwen3-TTS Base weights under Apache-2.0
and the synthetic reference recordings from
[ExNihilus/qwen3-tts-reference-voices](https://huggingface.co/ExNihilus/qwen3-tts-reference-voices),
revision `5103f8988ee936525fbfb6dc10061bbabd1d584e`, under CC0 1.0.
The catalog includes the publisher's exact reference transcripts and SHA-256 hashes.
The voice-pack download includes its CC0 legal text and NOTICE.
Audio and weights are stored separately in the user's application data.
