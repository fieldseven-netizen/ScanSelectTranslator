# ScanSelectTranslator (v1.0)

A lightweight, high-performance real-time translation overlay optimized for multi-monitor setups. Perfect for games and videos.
マルチディスプレイ環境に最適化された、軽量・高速なリアルタイム翻訳オーバーレイツール。ゲームや動画視聴に最適です。

---

## 🌟 English Description

### Key Features
- **Rock-Solid Center Alignment**: Stays perfectly centered on your main monitor without bleeding into secondary screens, regardless of Windows DPI settings.
- **High-Speed Windows Native OCR**: Uses built-in Windows 10/11 OCR for lightning-fast recognition and extremely small app size (no heavy AI frameworks like PyTorch).
- **Dynamic Customization**: Change overlay font size (10pt-48pt) and log font size on the fly.
- **Smart Line Breaking**: Automatically breaks lines at natural punctuation points for better readability.
- **Interactive Translation Log**: Click any line in the history to copy the original or translated text to your clipboard.
- **Global Support**: Automatically detects your OS language and supports multiple target languages (JA, EN, ZH, KO, FR, DE, ES).

### How to Use
1. **SCAN**: Capture the game screen.
2. **SELECT**: Drag on the preview image to select the area you want to translate.
3. **T-SCAN**: 3-second delayed scan. Gives you time to move your mouse back to the game.
4. **AS (Auto Show)**: Automatically shows the overlay when translation is ready.

---

## 🌟 日本語説明

### 主な特徴
- **不動の中央配置**: Windowsの拡大率設定に関わらず、サブモニターにはみ出すことなく、メインモニターのど真ん中に字幕を固定。
- **超軽量・高速なWindows標準OCR**: Windows 10/11内蔵のOCRエンジンを使用。PyTorch等の巨大ライブラリを排除し、数MB〜数十MBの軽量動作と高速起動を実現。
- **動的なカスタマイズ**: 字幕サイズ(10-48pt)やログの文字サイズを、使用中に即座に変更可能。
- **スマート改行**: 句読点や記号を考慮し、ゲーム画面を邪魔しない読みやすい位置で自動改行。
- **クリッカブル翻訳ログ**: 履歴をクリックするだけで、原文・訳文を個別にクリップボードへコピー。
- **グローバル対応**: OS言語を自動判別し、多様な翻訳先（日、英、中、韓、仏、独、西）に対応。

### 使い方
1. **SCAN**: 画面をキャプチャしてプレビューを表示。
2. **SELECT**: プレビュー上で翻訳したい範囲をマウスドラッグで選択。
3. **T-SCAN**: 3秒後にスキャンを実行。マウスをゲーム画面に戻す猶予を確保できます。
4. **AS (Auto Show)**: 翻訳完了時に自動的にオーバーレイを表示するか切り替えます。

---

## 🛠 Requirements / 動作環境
- **OS**: Windows 10 / 11 (Required for Native OCR)
- **Runtime**: Python 3.13+ (For development)

---
Developed with 💖 for Gamers worldwide.
