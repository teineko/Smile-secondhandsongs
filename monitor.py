#!/usr/bin/env python3
"""
指定URLのページを取得し、前回保存分と比較して差分があればメール通知するスクリプト。

必要な環境変数:
  TARGET_URL     監視対象のURL
  SMTP_HOST      例: smtp.gmail.com
  SMTP_PORT      例: 587
  SMTP_USER      送信に使うメールアドレス
  SMTP_PASSWORD  メールアドレスのパスワード（Gmail等はアプリパスワード推奨）
  MAIL_TO        通知を受け取るメールアドレス

状態ファイル（前回取得内容）は state/snapshot.txt に保存し、
GitHub Actions側でリポジトリにコミットして永続化する想定です。
"""

import os
import re
import smtplib
import sys
import difflib
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATE_DIR = Path("state")
STATE_FILE = STATE_DIR / "snapshot.txt"


def fetch_normalized_text(url: str) -> str:
    """ページ本文を取得し、比較しやすいよう空白等を正規化して返す"""
    resp = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0 (page-monitor-bot)"},
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # スクリプト/スタイル/ナビ等ノイズになりやすい要素は除外
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # 空行・余分な空白を整理（広告のカウンタや日時表示等で毎回微妙に変わる箇所の
    # 誤検知を減らすため、連続空白は1つにまとめる）
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def send_mail(subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    mail_to = os.environ["MAIL_TO"]

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = mail_to

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [mail_to], msg.as_string())


def main() -> int:
    url = os.environ.get("TARGET_URL")
    if not url:
        print("TARGET_URL が設定されていません", file=sys.stderr)
        return 1

    current = fetch_normalized_text(url)
    STATE_DIR.mkdir(exist_ok=True)

    if not STATE_FILE.exists():
        # 初回実行：比較対象がないので保存だけして終了
        STATE_FILE.write_text(current, encoding="utf-8")
        print("初回実行のため、現在の内容を保存しました。次回から差分チェックします。")
        return 0

    previous = STATE_FILE.read_text(encoding="utf-8")

    if previous == current:
        print("変更なし")
        return 0

    diff = list(
        difflib.unified_diff(
            previous.splitlines(),
            current.splitlines(),
            fromfile="前回",
            tofile="今回",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff)
    print("変更を検知しました。メールを送信します。")

    try:
        send_mail(
            subject=f"[ページ更新検知] {url}",
            body=f"以下のページに変更がありました:\n{url}\n\n--- 差分 ---\n{diff_text}",
        )
    except Exception as e:
        print(f"メール送信に失敗しました: {e}", file=sys.stderr)
        # メール失敗時も状態は更新し、次回以降の重複通知を避ける
        STATE_FILE.write_text(current, encoding="utf-8")
        return 1

    STATE_FILE.write_text(current, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
