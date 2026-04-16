# paper-reader

English README: [README.md](./README.md)

`paper-reader` は、学術論文 PDF を AI がそのまま読むよりも扱いやすい、安定した UTF-8 の `.txt` に変換するためのローカル Python CLI ツールです。

目的は論文内容の解釈ではありません。このツールは研究ワークフロー向けの PDF 抽出基盤として、本文抽出、ページ境界の保持、メタ情報の記録を担当し、その先の解釈や要約は別の AI ワークフローに任せます。

## 特徴

- 単一 PDF と PDF ディレクトリ一括処理の両方に対応
- `--input` でこのリポジトリ外の PDF を直接読める
- `--output` で別プロジェクト側へ `.txt` を直接書き出せる
- まず埋め込みテキスト抽出を試し、段階的にフォールバック
- 画像ベース PDF に対して OCR を任意で利用可能
- 1 論文 1 ファイルの安定した出力とメタ情報ヘッダ
- AI に読ませやすい `ai-readable` モードを搭載
- bbox を出さず、簡潔な図キャプション補足のみを任意出力可能
- 参考文献を本文から分離して保持
- 失敗を黙って捨てず、ログへ記録
- 将来的な `markdown` 出力拡張を考慮した設計

## ディレクトリ構成

```text
paper-reader/
  README.md
  README.ja.md
  pyproject.toml
  src/paper_reader/__init__.py
  src/paper_reader/__main__.py
  src/paper_reader/cli.py
  src/paper_reader/extractor.py
  src/paper_reader/models.py
  src/paper_reader/ocr.py
  src/paper_reader/utils.py
  tests/test_cli.py
  tests/test_extractor.py
  examples/sample_config.md
```

## セットアップ

### 基本インストール

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 主な依存

- `PyMuPDF`: 第一候補の抽出器
- `pdfplumber`: レイアウト寄りの第二候補
- `pypdf`: メタ情報やページ数取得の補助
- `typer`: CLI

### OCR を使う場合の追加依存

Python 側の追加依存を入れます。

```bash
pip install -e .[ocr]
```

さらにシステム依存も必要です。

- `tesseract`
- `ocrmypdf`

macOS で Homebrew を使う場合:

```bash
brew install tesseract ocrmypdf
```

これらが入っていない場合でも通常抽出は使えます。`--ocr` 使用時には CLI が明確なエラーをログに残します。

## 典型的な使い方

別研究プロジェクトの PDF ディレクトリを一括処理する:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable
```

単一 PDF を OCR 有効で処理する:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers/paper.pdf \
  --output /path/to/research-project/refs/papers_text \
  --ocr
```

独自 glob を使う:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --glob "*.PDF"
```

既存出力を上書きしつつ件数を制限する:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --force \
  --limit 10 \
  --verbose
```

簡潔な図キャプション補足を有効にする:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable \
  --include-visual-hints
```

table 系ブロックも残したい場合:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable \
  --include-tables
```

## 出力形式

1 論文につき 1 つの UTF-8 `.txt` を生成します。

例:

```txt
SOURCE: /abs/path/to/paper.pdf
EXTRACTED_AT: 2026-04-16T12:34:56+09:00
METHOD: pymupdf
PAGES: 12
MODE: ai-readable

===== PAGE 1 =====
...

===== PAGE 2 =====
...
```

生成された `.txt` は、研究プロジェクト側の背景資料やメモと一緒に AI に読ませることを想定しています。
`ai-readable` モードでは bbox ログはデフォルトで出さず、`--include-visual-hints` を付けた場合のみ簡潔な図キャプション補足を出力します。

## 抽出戦略

整形の美しさより、毎回の再抽出の安定性を優先します。

1. `PyMuPDF` による直接抽出
2. Unicode 正規化、front matter 削減、見出し整理、参考文献分離
3. `pdfplumber` によるレイアウト寄り抽出
4. `--ocr` 有効時の OCR フォールバック

実際に使われた抽出方式は各出力ファイルに記録されるため、後から抽出品質を評価できます。

## ログ

- 抽出失敗は出力先ディレクトリの `extract_errors.log` に記録
- `--force` を使わない限り既存出力は保持
- 一部失敗してもバッチ全体は継続

## テスト

実行:

```bash
pytest
```

確認している内容:

- 単一 PDF を処理できる
- ディレクトリ一括処理できる
- 出力先に `.txt` が作られる
- 存在しない入力パスで適切に失敗する
- CLI の `--ocr` フラグが通る

## 既知の限界

- 段組み PDF では読み順が崩れることがある
- 数式はプレーンテキスト近似に劣化しやすい
- 図表は意味構造まで復元しない
- スキャン PDF の品質はローカル OCR 環境に依存する
- 出版社由来の front matter が強い論文では、追加のヒューリスティクス調整が必要な場合がある

## 研究ワークフロー内での位置づけ

このリポジトリは共通の PDF 抽出基盤です。研究プロジェクトでは、典型的に次の流れを想定します。

1. プロジェクト側に `refs/papers/` のようなディレクトリを作る
2. そこへ元 PDF を置く
3. 別ディレクトリにある `paper-reader` から、その外部パスを `--input` として指定する
4. 出力先として `refs/papers_text/` のようなパスを `--output` に指定する
5. 生成した `.txt` を、その研究プロジェクトの背景資料と一緒に AI に読ませる

このツール自体は論文の解釈や要約を行いません。PDF を再利用可能なテキスト資産へ変換することに専念します。
