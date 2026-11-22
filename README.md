# MY MORNING RADIO (無料版)

iPhone向けの日本語モーニングラジオ。**有料API・APIキー不要**です。

## 稼働内容
- 埼玉県川口市と東京都品川区の朝・昼・夕・夜の天気（Open-Meteo）
- 最新ニュースの見出しと出典（Google News RSS）。**本文を確認していないため、ニュース解説と称しません**
- おすすめ曲1〜2曲のApple Music検索リンク（アプリから曲のフル再生はできません）
- ブラウザのWeb Speech APIで日本語読み上げ（iPhoneでは画面ロック・長時間連続再生は不安定な場合あり）
- GitHub Actionsが毎朝 JST 06:40 頃にデータを更新（GitHubのスケジュール実行は遅れる場合あり）

## セットアップ
1. GitHubの Settings → Pages → Build and deployment → Source を **GitHub Actions** にする。
2. Actions → Daily Morning Radio → Run workflow を押す。
3. Actions の結果が成功し、Pages のURLが表示されたら iPhone Safari で開く。
4. Safari の共有から「ホーム画面に追加」。日本語音声の利用はSafari側の対応に依存する。

Pages URL（設定後）: https://hiroki120530.github.io/my-morning-radio/

## 重要な制限
- **Googleカレンダーは未接続**。予定を空と断定せず「未確認」と案内します。個人予定を公共のGitHub Pagesへ平文で載せないよう、認証と暗号化が整うまでは自動取得しません。
- Apple Musicの曲はリンクから再生してください。曲がプレーヤー内部で再生・自動復帰する機能は未完成です。
- 音声は端末側で生成。MP3ファイルの自動生成ではありません。
- 元のApple Music 2,500曲のCSVはリポジトリにありません。候補曲は過去の紹介履歴を避けて選びますが、全リストとの照合は未完了。
- ニュースの情報源はRSS見出しであり、記事本文の裏取りや詳細な解説はしていません。
- 原稿の品質はテンプレート生成のため、以前の手書き風原稿より簡潔です。

## 構成
- `scripts/generate.py`：標準ライブラリだけでデータ取得・原稿生成
- `site/index.html`：再生画面
- `site/episode.json`：当日の番組データ（公開情報のみ）
- `.github/workflows/daily.yml`：スケジュール実行とPages配信

## 運用上の注意
現状は個人の予定やメールを公開リポジトリ・Pagesに出さない安全優先の基礎版です。機密情報の連携は専用の非公開環境・暗号化・アクセス制御を整備してからにしてください。
