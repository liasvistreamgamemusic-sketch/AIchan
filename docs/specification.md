# AIちゃん — デスクトップAIキャラクターコンパニオン 仕様書

> バージョン: 0.1 (ドラフト)
> 最終更新: 2026-06-30
> ステータス: 設計フェーズ

デスクトップ上に常駐する小さなキャラクターウィンドウ。キャラクターは喋り、画面を見てコメントし、こちらの声を聞き取り、会話を記憶する。ローカルLLM(LMStudio)を頭脳に、ローカルTTS(irodoriTTS)を声に、ローカルWhisperを耳に使う、完全ローカル動作を基本とするAIコンパニオン。

---

## 1. ゴールと非ゴール

### 1.1 ゴール
- Windows で確実に動作する(Mac も可能なら対応、ただし優先度は低い)。
- デスクトップ常駐の小さなウィンドウにキャラクターが**常に表示**される。
- キャラクターが**音声で喋る**(TTS)。感情に応じて立ち絵が切り替わる。
- **画面を時々読み取り**、Visionモデルで「〇〇してるんだね、楽しそう!」のようなコメントを発話する。
- ユーザーが**話しかけられる**(音声入力 + テキスト入力)。
- **会話・ユーザー情報・キャラクターのペルソナを永続化**し、文脈を保ちつつ、肥大化を防ぐため定期的に**情報を圧縮(要約)**する。キャラの一貫性は維持する。
- 主要機能は**オン/オフ切り替え可能**(画面読み取り・自発発話など)。
- 将来的に **Discord** 連携で会話できる。

### 1.2 非ゴール(現フェーズでは扱わない)
- クラウドLLM/クラウドTTSへの依存(あくまでローカル前提。OpenAI互換APIの口だけ用意)。
- 高度な3D/Live2Dアニメーション(まずは静止立ち絵の感情差し替えから。Live2Dは将来拡張)。
- マルチユーザー同時利用、アカウント管理、課金。

---

## 2. 技術スタック(推奨)

| 領域 | 採用候補 | 理由 |
|---|---|---|
| 言語 | **Python 3.11+** | Whisper / Vision / 画面キャプチャ / SQLite / Discord を1言語で完結。ユーザーのPython・ML資産と親和。 |
| GUI / ウィンドウ | **PySide6 (Qt6)** | 透過・最前面・枠なし・常駐トレイ・マルチモニタを標準サポート。立ち絵差し替えが容易。 |
| LLM接続 | **`openai` Python SDK**(`base_url` をLMStudioへ向ける) | LMStudioはOpenAI互換API。Vision対応モデル1つで会話+画面理解を兼用。**採用モデル: Gemma 3 12B(マルチモーダル/画像入力対応)**。 |
| TTS | **Irodori-TTS v3**(`Irodori-TTS-Server` = **OpenAI TTS API互換**サーバ) | 感情表現・キャラ声に強く対話エージェント向き。MIT(商用可)。絵文字で感情制御。`POST /v1/audio/speech`(port 8088)。フォールバックに **AivisSpeech**(GPU不要)。 |
| STT(音声認識) | **whisper.cpp(Vulkanバックエンド)** | `small`/`medium` を切替。**Vulkanで Windows / Linux 両対応**(ROCm/CUDA非依存)。faster-whisperは代替。 |
| GPUバックエンド | **LLM/STT = Vulkan、TTS = ROCm** | LLM(LMStudio Vulkan)・STT(whisper.cpp Vulkan)はVulkanでWin/Linux両対応。**Irodori-TTSはPyTorch製のためVulkan不可→ROCm**で動かす(別プロセスの専用uv環境 `--extra rocm`)。**RX 9070 XT は WSL・native Windows 両方でROCm動作実証あり**。プロセス分離(`§9.1`)により両バックエンドは綺麗に共存。 |
| 音声入出力 | `sounddevice` + `webrtcvad`(VAD) | マイク録音、無音区切り、再生。 |
| 画面キャプチャ | `mss` | 高速スクリーンショット。マルチモニタ対応。 |
| DB | **SQLite**(`sqlite3` / `SQLAlchemy`) + ベクトル検索は `sqlite-vec` or `chromadb` | 会話・ペルソナ・記憶の永続化と意味検索。 |
| スケジューリング | `APScheduler` | 自発発話・画面読み取り・記憶圧縮の定期実行。 |
| Discord | `discord.py` | Bot連携。 |
| 設定 | `pydantic-settings` + `config.yaml` | 型安全な設定。 |
| パッケージング | **PyInstaller**(Windows `.exe`) | 配布。 |

> **代替案**: UIをWeb技術で作りたい場合は **Tauri / Electron + Pythonサイドカー** 構成も可能。ただし2プロセス間IPCの複雑さが増すため、初期は Python + PySide6 単一プロセス(+ワーカースレッド)を推奨する。

---

## 3. 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                      AIちゃん (Python プロセス)                │
│                                                               │
│  ┌───────────────┐   ┌──────────────────┐  ┌──────────────┐  │
│  │   UI Layer     │   │  Orchestrator     │  │  Scheduler   │  │
│  │ (PySide6)      │◄─►│  (対話制御の中核)  │◄─►│ (APScheduler)│  │
│  │ - 立ち絵表示    │   │  - 入力ルーティング│  │ - 自発発話    │  │
│  │ - 吹き出し/字幕 │   │  - プロンプト構築  │  │ - 画面読取    │  │
│  │ - 設定画面      │   │  - 感情→立ち絵     │  │ - 記憶圧縮    │  │
│  │ - トレイ       │   │  - TTS再生制御     │  └──────────────┘  │
│  └───────────────┘   └─────────┬────────┘                     │
│                                 │                              │
│   ┌──────────┬──────────┬───────┼────────┬──────────┐         │
│   ▼          ▼          ▼       ▼        ▼          ▼         │
│ ┌──────┐ ┌──────┐  ┌────────┐ ┌──────┐ ┌──────┐ ┌────────┐   │
│ │ LLM  │ │ STT  │  │ Vision │ │ TTS  │ │Screen│ │ Memory │   │
│ │Client│ │Whisper│ │(LLM兼用)│ │irodori│ │ mss  │ │  DB    │   │
│ └──┬───┘ └──────┘  └────────┘ └──┬───┘ └──────┘ └───┬────┘   │
└────┼─────────────────────────────┼──────────────────┼────────┘
     │                             │                  │
     ▼                             ▼                  ▼
 LMStudio(OpenAI互換)        irodoriTTS サーバ      SQLite + ベクトルDB
     │
     └─ Discord 連携 (discord.py) ──► 同じ Orchestrator を共有
```

### 3.1 コアモジュール責務
- **Orchestrator(対話制御コア)**: すべての入力(音声・テキスト・画面・自発トリガー・Discord)を受け取り、記憶を取り出してプロンプトを構築 → LLM呼び出し → 構造化出力(セリフ+感情+イントネーション)をパース → 立ち絵更新 + TTS再生 + DB保存、を一貫制御。UIとは疎結合(シグナル/イベント)。
- **LLM Client**: OpenAI互換クライアント。テキスト/Vision両対応。ストリーミング受信。
- **STT Worker**: マイク→VAD→Whisper。確定テキストを Orchestrator へ。
- **Vision**: スクリーンショットを base64 画像としてLLMへ添付(LLM Clientと同一モデル)。
- **TTS Client**: irodoriTTSへ声色パラメータ付きで合成要求 → 音声再生。感情/イントネーション指定を反映。
- **Memory**: 会話ログ・ユーザープロファイル・ペルソナ・要約記憶の CRUD と意味検索、圧縮処理。
- **Scheduler**: 定期ジョブ(自発発話・画面読み取り・記憶圧縮)。

---

## 4. キャラクター表示ウィンドウ

### 4.1 ウィンドウ仕様
- **枠なし・透過・常に最前面**(`Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`)。
- 背景透過(`Qt.WA_TranslucentBackground`)でキャラクター画像のみが浮く。
- **ドラッグで移動**可能。位置・サイズは設定に永続化。マルチモニタ対応。
- 右クリック / トレイアイコンからメニュー(設定、ミュート、終了、機能オン/オフ)。
- クリックスルー設定(任意): キャラの透明部分はクリックを下のウィンドウへ透過。
- 小さいウィンドウ。デフォルト幅 ~256–384px、立ち絵のアスペクト比に追従。

### 4.2 表示要素
- **立ち絵レイヤー**: 現在の感情に対応する画像を表示(`§5`)。差し替え時にクロスフェード。
- **字幕 / 吹き出し**: 発話テキストを下部または横に表示(TTSと同期、字送り)。オン/オフ可。
- **入力欄(任意表示)**: ホットキーやクリックでテキスト入力欄を出してタイプ会話。
- **状態インジケータ**: 「聞いている」「考えている」「喋っている」の小さな表示(マイクアイコン等)。
- **口パク(簡易)**: TTS再生中に「閉/開」2枚 or 音量連動で口画像を切替(将来Live2Dへ拡張可)。

### 4.3 インタラクション
- ホットキー(グローバル): プッシュ・トゥ・トーク(押している間だけ録音)/ ミュート切替 / テキスト入力呼び出し。
- 常時リスニングモード(VADで自動区切り)とプッシュ・トゥ・トークを選択可。
- キャラをクリックすると反応(撫でる等のミニリアクション、将来拡張)。

---

## 5. キャラクター画像(立ち絵)仕様

> 画像生成プロンプトの全文と運用は **[character-image-prompts.md](character-image-prompts.md)** を参照。ここでは仕様の枠組みを定義する。

### 5.1 フォーマット
- ギャルゲー風の**バストアップ(上半身〜胸上、顔中心)**立ち絵。
- **基準解像度 1024×1536**(縦長)。表示時にスケール。
- 同一キャラ・同一構図・同一画風で、**表情(感情)だけが差し替わる**セットを用意する(一貫性が最重要)。
- **2段階の素材管理**:
  - **素材(green screen, RGB)**: `character/{character_id}/{emotion}.png` … nano banana出力(単色グリーン背景)。手付かずの原本。
  - **配信用(透過, RGBA)**: `assets/characters/{character_id}/{emotion}.png` … 背景除去後の透過PNG。**アプリが読むのはこちら**。
- 命名は `{emotion}.png`(`§5.2` のラベル)。例: `character/sumire/neutral.png` → 背景除去 → `assets/characters/sumire/neutral.png`。
- **現状: `character/sumire/` に全14枚(green screen)あり。背景除去パイプライン未実装**(`§5.5`)。

### 5.2 感情ラベル(立ち絵のバリエーション)
最小セット(MVP)とフルセットを定義。LLMの感情出力(`§7.3`)とこのラベルを対応付ける。

| ラベル | 用途 |
|---|---|
| `neutral` | 通常・待機 |
| `happy` | 嬉しい・楽しい |
| `smile` | 微笑み・穏やか |
| `excited` | 興奮・テンション高 |
| `laugh` | 大笑い |
| `surprise` | 驚き(ファイル名 `surprise.png`) |
| `sad` | 悲しい |
| `worried` | 心配・困り |
| `angry` | 怒り・ぷんぷん |
| `pout` | むくれ・ジト目 |
| `shy` | 照れ |
| `sleepy` | 眠い・まったり |
| `thinking` | 考え中 |
| `wink` | ウインク |

> MVPは `neutral / happy / surprise / sad / shy / thinking` の6種でも開始可能。未定義感情は最も近いラベルへフォールバック(マッピング表をコードに持つ)。すみれの全14感情は揃っている。

### 5.3 容姿の後付け対応(重要)
- キャラクターの**容姿(髪・目・服・体型など)の定義はプロンプト内の差し替え変数**として分離する。
- これにより「容姿は後々指示に追加・変更できる」要件を満たす。詳細は [character-image-prompts.md](character-image-prompts.md) の **キャラクター定義ブロック**を参照。
- 容姿を変えても**構図・画風・表情の付け方は固定**し、感情セット全体で一貫させる。

### 5.4 口パク用差分(任意)
- 各感情につき口「閉/開」2枚、または口部分のみのオーバーレイ素材を用意すると簡易口パクが可能。
- MVPでは省略可(TTS中はわずかに上下に揺らす等の代替演出)。

### 5.5 背景除去パイプライン(green screen → 透過PNG)— **実装済み**
nano banana出力は**単色グリーン背景のRGB**。アプリ表示には透過が必要なため、バッチ変換する。
- **手法 = クロマキー**([tools/remove_bg.py](../tools/remove_bg.py))。`greenness = G - max(R,B)` でアルファを生成し、なめらかな境界 + despill(緑かぶり除去)。
  - 補足: 当初 `rembg`(u2net + alpha matting)を試したが、**均一グリーン背景では灰色ハロー/紫フリンジが出て不適**だった。背景が単色なら**クロマキーの方が圧倒的に綺麗**(ハロー・フリンジ無し)。重いnumba依存も不要。
- **入出力**: `character/{id}/*.png`(原本)→ `assets/characters/{id}/*.png`(RGBA透過)。原本は再処理のため保持。アプリが読むのは `assets/` 側。
- **実行**: `uv run --python 3.12 --with pillow --with numpy python tools/remove_bg.py --id sumire`。閾値は `--low/--high` で調整可。将来キャラ追加・差し替え時も同スクリプトで再生成。
- **すみれ: 全14枚変換済み**(RGBA、各約38%透明、不透明部の緑残り0)。
- **品質チェック**: 縁の緑残り・髪の透け・半透明境界を確認(`character-image-prompts.md` `§5`)。

---

## 6. 画面読み取り(Vision)コメント機能

### 6.1 動作
- Schedulerが**ランダム間隔**(例: 平均5〜15分、設定可。ジッターあり)でトリガー。
- `mss` でアクティブモニタのスクリーンショットを取得 → 縮小 → base64化。
- Vision対応LLMに「画面を見て、フレンドリーに一言コメントして」というシステム指示+画像を渡す。
- 出力は通常の発話パイプライン(`§7`)を通り、感情つきで立ち絵更新 + TTS発話。
- 例: 「コード書いてるんだね、集中してて偉い!」「動画見てるの? 楽しそう〜」

### 6.2 プライバシー / 設定
- **オン/オフ切替必須**(デフォルトはオフ or 初回同意制を推奨)。
- **除外設定**: 特定アプリ/ウィンドウタイトルにマッチする場合はキャプチャしない(パスワード管理、金融、プライベート等)。
- スクリーンショットは**LLMへ送るのみで原則ディスク保存しない**(デバッグ時のみ任意保存)。
- キャプチャ頻度・対象モニタ・縮小解像度を設定可能。
- LMStudioがローカルなので画像は外部送信されない(ローカル完結)。

---

## 7. LLM連携と構造化出力

### 7.1 接続
- LMStudio の OpenAI互換エンドポイント(例 `http://localhost:1234/v1`)へ `openai` SDK で接続。
- **採用モデル: Gemma 3 12B**(マルチモーダル)。**Vision対応モデル1つ**で、テキスト会話と画面理解の両方を担う。
- 注意: Gemma系はOpenAI互換APIの `response_format`(JSONスキーマ強制)やツール呼び出しに完全対応とは限らないため、出力フォーマットは**プロンプト指示 + 緩いJSONパーサ + リトライ**で堅牢化する(`§7.3`)。画像はOpenAI互換の `image_url`(base64 data URI)で添付。
- ストリーミング受信で字幕を逐次表示、TTSは文単位でチャンク合成し体感遅延を削減。

### 7.2 プロンプト構成(レイヤー)
1. **System / ペルソナ**: キャラクターの性格・口調・世界観(DBの `persona` から)。
2. **長期記憶サマリ**: 圧縮済みの要約記憶(`§8`)。
3. **関連記憶(検索)**: 直近の話題に意味的に近い過去会話の断片(ベクトル検索 top-k)。
4. **ユーザープロファイル**: 名前・好み・呼び方など。
5. **直近会話**: 最新Nターン(生ログ)。
6. **現在の入力**: 音声/テキスト/画面画像/自発トリガーの種別と内容。
7. **出力フォーマット指示**: 下記の構造化JSON(`§7.3`)を必ず返すよう指示。

### 7.3 構造化出力(セリフ + 感情 + イントネーション)
リアルさ再現のため、LLMには**セリフ本文に加えて感情・話し方メタ情報**を同時出力させる。Vision対応かつJSON出力を安定させるため、`response_format`(JSON)またはツール呼び出し/明示フォーマットを利用。

```json
{
  "speech": "コード書いてるんだね、集中してて偉いっ!",
  "speech_tts": "コード書いてるんだね、集中してて偉いっ!😊✨",
  "emotion": "happy",
  "emotion_intensity": 0.8,
  "tts": {
    "speed": 1.05,
    "cfg_scale_text": 1.0,
    "cfg_scale_speaker": 1.0
  },
  "actions": ["wink"],
  "memory_note": "ユーザーはよくコードを書いている"
}
```

- `speech`: 字幕表示用テキスト(絵文字なし)。
- `speech_tts`: **Irodori-TTSへ渡す、感情絵文字を埋め込んだ発話テキスト**(`§9.2` のスタイル制御。😊=嬉しい/😭=泣き/🤧=咳/囁き等を本文に挿入)。抑揚・演技はこの絵文字で表現する。
- `emotion` / `emotion_intensity`: 立ち絵選択(`§5.2`)と表現強度。
- `tts`: Irodori-TTSへ渡すパラメータ(`§9.2`)。`speed` と必要に応じ `cfg_scale_*`。voiceは基準設定を使用。
- `actions`: 任意の演出(ウインク、首かしげ等)。
- `memory_note`: 記憶に残すべき要点(あれば)。Memoryモジュールが取り込む。

> Irodoriはピッチ/SSML指定を持たない想定のため、`pitch`/`emphasis`/`pauses` のようなSSML的フィールドは廃し、**感情は `speech_tts` の絵文字**に集約する。LLMには「感情に応じた絵文字を `speech_tts` に付ける」ことをプロンプトで指示する。

> 小型ローカルモデルでJSONが崩れる場合に備え、**緩いパーサ + リトライ + フォールバック**(本文のみ抽出し emotion=neutral)を実装する。

---

## 8. 記憶 / データベース

### 8.1 保存するもの
- **ペルソナ(persona)**: キャラの不変的人格・口調・設定。**圧縮対象外**。安易に変化させない(キャラ崩壊防止)。
- **ユーザープロファイル(user_profile)**: 名前・呼び方・好み・嫌い・重要事実。
- **会話ログ(messages)**: 全発話の生ログ(role, text, emotion, timestamp, source: voice/text/screen/proactive/discord)。
- **要約記憶(memory_summaries)**: 期間/トピック単位に圧縮された要約。長期文脈用。
- **エピソード記憶 + ベクトル(memory_vectors)**: 検索用の埋め込み。

### 8.2 スキーマ(SQLite、概略)
```sql
CREATE TABLE persona (
  id INTEGER PRIMARY KEY, character_id TEXT,
  content TEXT,            -- 人格・口調・世界観(編集UIから更新)
  updated_at TIMESTAMP
);

CREATE TABLE user_profile (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT, updated_at TIMESTAMP
);

CREATE TABLE messages (
  id INTEGER PRIMARY KEY, ts TIMESTAMP, role TEXT,      -- user / assistant
  source TEXT,            -- voice / text / screen / proactive / discord
  text TEXT, emotion TEXT, meta JSON
);

CREATE TABLE memory_summaries (
  id INTEGER PRIMARY KEY, period_start TIMESTAMP, period_end TIMESTAMP,
  topic TEXT, summary TEXT, salience REAL, updated_at TIMESTAMP
);

CREATE TABLE memory_vectors (         -- sqlite-vec / chromadb 等
  id INTEGER PRIMARY KEY, ref_type TEXT, ref_id INTEGER,
  embedding BLOB, text TEXT
);
```

### 8.3 情報の圧縮(肥大化対策)— 要件の核心
入力に過去全会話を毎回入れると生成が重くなるため、**階層的記憶圧縮**を行う:

1. **生ログは保持**しつつ、プロンプトには入れない(検索対象としてのみ使用)。
2. **直近Nターンのみ生で投入**(短期記憶ウィンドウ)。
3. **ローリング要約**: 一定ターン/時間ごとに、古い会話をLLM自身に要約させ `memory_summaries` に格納。要約後の生ログはプロンプトから外す。
4. **再要約(階層化)**: 日次→週次→月次のように、要約をさらに上位要約へ畳み込み、総量を一定に保つ。
5. **意味検索(RAG)**: 現在の話題に関連する過去要約/エピソードを top-k だけ取り出して投入。全件は入れない。
6. **重要度(salience)管理**: ユーザーの重要事実(名前・好み・約束)は専用テーブルへ昇格し、要約に埋もれさせない。

#### 8.3.1 キャラ一貫性の保護(重要)
- **圧縮対象は「会話内容・ユーザー情報」であり、ペルソナ(キャラ人格)は圧縮・改変しない**。
- 要約処理のプロンプトには「キャラクターの口調・性格は変更しないこと。事実と出来事のみを要約する」と明示。
- ペルソナ更新は**ユーザーが明示した時のみ**(自動で人格を書き換えない)。
- 要約は「三人称の事実記録」として保存し、キャラの語り口を混入させない。

#### 8.3.2 圧縮トリガー
- `APScheduler` で、(a) 会話ターン数が閾値超過、(b) アイドル時、(c) 定期(例: 毎深夜)に圧縮ジョブを実行。

---

## 9. TTS(irodoriTTS)連携

採用: **Irodori-TTS v3**(`Aratako/Irodori-TTS-500M-v3`、MIT)。同梱の **`Irodori-TTS-Server`** が **OpenAI TTS API互換**なので、LLM接続(`§7`)と同じ `openai` SDKの作法でTTSも叩ける。

### 9.1 接続 — **HTTPサーバ方式(別プロセス)を採用**
- `Irodori-TTS-Server` を**独立した uv 環境・別プロセス**でローカル起動する。
  - 起動例: `uv run python -m irodori_openai_tts --host 127.0.0.1 --port 8088`(GPUは `uv sync --extra rocm`)。
  - 理由: TTSはPyTorch(ROCm)、STT/LLMはVulkan。依存・VRAMを分離し、巻き込みクラッシュを防ぐ。Discord等の他クライアントからも同サーバを再利用できる。
- **主なAPI**: `POST /v1/audio/speech`(合成)、`GET /v1/audio/voices` / `POST /v1/audio/voices`(声の一覧・登録)、`GET /health`、`GET /v1/models`。
- **ライフサイクル**: アプリ起動時に `subprocess` でTTSサーバを自動起動 → `/health` 確認後にリクエスト。終了時に停止、落ちたら自動再起動。
- アプリは合成済み音声(wav/mp3/flac/opus/aac/pcm)を受け取り `sounddevice` で再生。再生中はTTS状態を立て、口パク・字幕同期。
- `§9.3` の `TTSBackend` 抽象の実装を「Irodori-TTS OpenAI互換クライアント」とする。

### 9.2 声色・感情コントロール(アプリ上で制御)
Irodori-TTSの制御は **(a) 声(voice)指定**、**(b) リクエストパラメータ**、**(c) テキスト中の絵文字による感情/スタイル制御** の3系統。設定UIとLLM出力(`§7.3` の `tts`)から以下を制御:
- **voice**: 登録済みボイス(ファイルID)を選択。`POST /v1/audio/voices` で参照音声をアップロードしてキャラ声を作成・固定。
- **speed**: 話速 0.25〜4.0(デフォルト1.0)。
- **irodori 詳細オプション**: `num_steps`(拡散ステップ=品質と速度のトレード)、`seed`(再現性)、`cfg_scale_text`(テキスト追従強度)、`cfg_scale_speaker`(話者追従強度)。
- **感情/スタイル = 絵文字制御**: 😭(泣)🤧(咳)👂😮‍💨(囁き)など、**感情を絵文字としてセリフテキストに埋め込む**ことで抑揚・演技を付与する。これがIrodoriの肝。
  - → LLMの構造化出力(`§7.3`)では、`emotion` ラベルや本文に**感情絵文字を付与した発話テキスト**を返させ、TTSへそのまま渡す(`§7.3` を絵文字対応に拡張)。
- ユーザーがUIで設定した「基準声色(voice/speed/cfg)」に、LLMが返す感情を**相対的に上乗せ**(基準から逸脱しすぎない範囲でクランプ)。
- 注意: Irodoriにピッチ/SSMLの直接指定は無い想定。抑揚は**絵文字 + cfg_scale + 参照音声**で表現する。SSML前提の設計はしない。

### 9.3 抽象化
- TTSバックエンドは **インターフェース化**(`TTSBackend`)し、**Irodori-TTS を主実装**、**AivisSpeech をフォールバック**(GPU不要・低レイテンシ選択肢)として登録。
- `§7.3` の `tts` / 感情フィールドと、Irodoriの voice/speed/irodoriオプション/絵文字 とのマッピング表を実装時に確定する。

---

## 10. 音声入力(STT / Whisper)

- **whisper.cpp(Vulkanバックエンド)** を採用(`small`/`medium` を設定で切替)。**Vulkanで Windows native / WSL・Linux の両方を同一経路でカバー**(ROCm/CUDA非依存)。CPUフォールバックも可。
  - 性能: 推論用途のVulkanはROCm比で実用上の差は小さく、Whisperのリアルタイム書き起こしに十分。
  - 代替: 必要なら faster-whisper(CTranslate2)も選べるが、ROCm/CUDA依存で両OS統一の利点が薄れるため非推奨。P0でVulkan実機検証する。
- マイク入力 → `webrtcvad` で発話区間検出 → 確定区間をWhisperへ → テキスト化 → Orchestratorへ。
- モード: **常時リスニング(VAD)** / **プッシュ・トゥ・トーク(ホットキー)** を選択。
- ウェイクワード(任意・将来): 「ねえ」「〇〇ちゃん」等で起動。MVPでは省略可。
- 言語は日本語優先(多言語設定可)。精度と速度のトレードオフを設定で調整。

---

## 11. 自発発話(たまに話しかける)

- Schedulerが**アイドル検知 + ランダム間隔**で発話トリガーを生成。
- トリガー種別: 時間帯あいさつ(おはよう/おやすみ)、長時間操作への気遣い、画面コメント、雑談、過去の話題の蒸し返し(記憶活用)。
- **連発防止**: クールダウン、ユーザーが取り込み中(全画面/ゲーム/会議アプリ)なら抑制、夜間サイレント等のルール。
- オン/オフ + 頻度設定可。

---

## 12. Discord連携(将来)

- `discord.py` Bot として、同じ Orchestrator・記憶DBを共有。
- DM または指定チャンネルでテキスト会話(同一キャラ・同一記憶)。
- 任意: ボイスチャンネルでTTS発話 / 音声認識(拡張)。
- デスクトップとDiscordで**記憶を共有**するため、`source=discord` として messages に記録。
- フェーズ後半で着手(MVPには含めない)。

---

## 13. 設定 / トグル一覧

`config.yaml`(+ 設定UI)で管理。主な項目:
- LLM: `base_url`, `model`, `api_key`(LMStudioはダミー可), `temperature`, `max_tokens`。
- TTS: バックエンド, 話者, 基準 speed/pitch/energy/style, 音量。
- STT: モデルサイズ, デバイス(cuda/cpu), モード(VAD/PTT), ホットキー。
- 画面読み取り: **オン/オフ**, 頻度(min/max間隔), 対象モニタ, 縮小解像度, 除外アプリ。
- 自発発話: **オン/オフ**, 頻度, 静音時間帯, クールダウン。
- 表示: ウィンドウ位置/サイズ, 字幕オン/オフ, クリックスルー, キャラID。
- 記憶: 短期ウィンドウサイズ, 圧縮間隔, RAG件数(top-k)。
- Discord: トークン, 対象チャンネル, オン/オフ。
- プライバシー: スクリーンショット保存オン/オフ(デフォルトオフ)。

---

## 14. ディレクトリ構成(案)

```
AIchan/
├─ docs/
│  ├─ specification.md            # 本書
│  └─ character-image-prompts.md  # 立ち絵生成プロンプト集
├─ aichan/
│  ├─ __init__.py
│  ├─ main.py                     # エントリポイント
│  ├─ config.py                   # 設定(pydantic-settings)
│  ├─ orchestrator.py             # 対話制御コア
│  ├─ ui/                         # PySide6: ウィンドウ・字幕・設定・トレイ
│  ├─ llm/                        # OpenAI互換クライアント・プロンプト構築・JSONパーサ
│  ├─ vision/                     # 画面キャプチャ + Vision要求
│  ├─ stt/                        # faster-whisper + VAD
│  ├─ tts/                        # TTSBackend 抽象 + irodoriTTS 実装
│  ├─ memory/                     # DB・要約圧縮・検索
│  ├─ scheduler/                  # 自発発話・画面読取・圧縮ジョブ
│  ├─ settings.py                 # config.yaml(AppConfig)
│  └─ discord_bot/                # Discord Bot(discordパッケージとの名前衝突回避)
├─ assets/
│  └─ characters/
│     └─ sumire/                  # neutral.png, happy.png, ...(透過PNG)
├─ data/                          # SQLite DB, ログ(gitignore)
├─ config.yaml
├─ pyproject.toml
└─ README.md
```

---

## 15. 開発フェーズ(ロードマップ)

> 状態: P1〜P8 のコードを実装済み(各サブシステムは graceful degradation 対応)。
> 残: 実機での疎通(LMStudio/Irodori-TTS/Whisper)、声の登録・チューニング、.exe化。

| フェーズ | 内容 | 状態 |
|---|---|---|
| **P0** | 仕様確定・スタック検証 | ✅ 仕様確定 / 実機疎通は残 |
| **P1** | 表示MVP(透過・最前面・立ち絵・感情・字幕) | ✅ 実装 + Windows実機確認 |
| **P2** | 会話MVP(テキスト→LLM→構造化出力→立ち絵+字幕、記憶) | ✅ 実装(`llm/`, `orchestrator.py`, `memory/`) |
| **P3** | 音声(TTS発話・Whisper入力・声色) | ✅ 実装(`tts/`, `stt/`)/ 実機疎通は残 |
| **P4** | 画面読み取り(Visionコメント・除外) | ✅ 実装(`vision/`) |
| **P5** | 自発発話(スケジューラ・静音時間) | ✅ 実装(`scheduler/`) |
| **P6** | 記憶圧縮(ローリング要約・階層化・RAG・キャラ保護) | ✅ 実装(`memory/summarize.py`, `store.py`) |
| **P7** | 仕上げ(口パク・状態表示・入力欄) | ✅ 実装 / 設定UI・.exe化は残 |
| **P8** | Discord(Bot連携・記憶共有) | ✅ 実装(`discord_bot/`) |

---

## 16. プラットフォーム戦略(Windows / WSL 両対応)

開発は WSL、リリースは **native Windows** を本番ターゲットとする。両環境でアプリを起動できるよう、**クロスプラットフォーム実装 + プラットフォーム抽象層(capability検出)** で設計する。

### 16.1 方針
- **コアロジックは共通**: LLMクライアント、記憶DB、プロンプト構築、要約圧縮、TTSクライアント、STT、Orchestrator。OS非依存に保つ(`pathlib`使用、Linux固有依存を避ける)。
- **OS密着部分は抽象層で差し替え**: ウィンドウ/トレイ/ホットキー/クリックスルー、画面キャプチャ、音声I/O、GPUバックエンド。
- **GPUは Vulkan で統一**(`§2`)。Windows native / WSL・Linux のどちらでも同一経路。ROCm-on-WSL と DirectML-on-Windows の二重管理を回避。
- **capability フラグ**: 起動時に実行環境を判定し、その環境で不可能な機能は自動で無効化(例: WSLからはWindowsデスクトップのスクリーンキャプチャ・システムトレイが制限されるため、該当機能をオフにしてもロジック・会話は動く)。

### 16.2 環境別の機能可否(目安)

| 機能 | native Windows | WSL(WSLg) | 備考 |
|---|---|---|---|
| コア会話 / 記憶 / LLM / TTS / STT | ✅ | ✅ | OS非依存。WSLからWindowsのLMStudio/TTSへはホストIPで接続 |
| Vulkan GPU(LLM/Whisper) | ✅ | ✅ | 両対応が統一の狙い |
| 透過・最前面キャラウィンドウ | ✅ フル | △ 制限あり | WSLgはLinuxウィンドウとして表示。挙動は限定的 |
| システムトレイ / グローバルホットキー | ✅ | △/❌ | 環境依存。capabilityで自動判定 |
| **画面読み取り(Windowsデスクトップ)** | ✅ | ❌ | WSLからはWindows画面が見えない。WSLでは自動オフ |
| マイク音声入力 / 再生 | ✅ | △ | WSLgオーディオは不安定。実用はWindows |

> **重要**: WSLだけでは「常駐キャラ・画面読み取り・音声」という本アプリの本質を検証できない。OS密着機能(P1のウィンドウ、P3の音声、P4の画面読み取り)は **native Windows 実機で開発・テスト**する。WSLはコアロジック開発とLinux版TTS/Whisperの実験場として併用する。

---

## 17. 未確定事項 / 確認したいこと

- ~~LMStudioで使う**Vision対応モデルの具体名**~~ → **確定: Gemma 3 12B**。残課題: VRAM/速度の実測、JSON出力の安定性検証。
- ~~立ち絵の**生成手段**~~ → **確定: nano banana(Gemini 2.5 Flash Image)**。残課題: **透過PNG(アルファ)書き出し可否**と、不可なら背景除去工程の要否。最終的な**容姿の確定**は別途。
- ~~**irodoriTTS** の提供形態 / GPU / API~~ → **確定**: Irodori-TTS v3(MIT)を採用。**`Irodori-TTS-Server`(OpenAI TTS API互換、port 8088)** をHTTPサーバ方式で接続(`§9.1`)。**ROCmでGPU動作、RX 9070 XT は WSL/native Windows 両方で実証あり**(CPUは1文約2分で実用外→GPU前提)。感情は**絵文字制御**(`§9.2`)。残課題: 実機での声(voice)登録・基準声色のチューニング、レイテンシ実測。
- ~~Whisperを動かす**GPU環境**~~ → **確定: whisper.cpp の Vulkan バックエンド(Windows/WSL両対応)**。残課題: Vulkan実機検証(両OS)。
- パッケージング形態(インストーラ配布 or ソース実行)。native Windows でのビルドを基本とする。

> これらは [character-image-prompts.md](character-image-prompts.md) と併せて、P0で確定させる。
