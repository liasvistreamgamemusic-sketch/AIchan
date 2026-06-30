# キャラクター立ち絵 生成プロンプト集

> 対象: [specification.md](specification.md) `§5 キャラクター画像(立ち絵)仕様`
> 採用ツール: **nano banana(Gemini 2.5 Flash Image)**
> 目的: ギャルゲー風のバストアップ立ち絵を、**同一キャラ・同一構図・同一画風のまま「表情(感情)だけ」差し替えたセット**として生成する。容姿は後から差し替え可能な変数として分離する。

---

## 0-A. nano banana 向けの作法(最重要)

nano banana はSD系の「タグ羅列」より、**自然言語の指示文**と**参照画像によるキャラ一貫性**が得意。そこで本プロジェクトの正規ワークフローは以下とする。

### 推奨ワークフロー(参照画像方式)
1. **基準立ち絵 `neutral` を1枚だけ確定生成**する(後述の自然言語プロンプト)。これがキャラの「正典(canon)」。
2. 以降の各感情は、**`neutral` を参照画像として渡し**、「**表情だけを〇〇に変え、それ以外(髪・顔立ち・服・構図・画風・ライティング)は完全に同一に保つ**」と指示して生成する。
   - これによりnano banana のキャラ一貫性が最大限効き、セットのブレを最小化できる。
3. 全感情を `neutral` 由来で派生 → `assets/characters/aichan/{emotion}.png` に保存。
4. 容姿変更時は、まず `neutral` を作り直し → 同じ手順で全感情を派生し直す(`§6`)。

### 注意点
- **透過背景**: nano banana は真のアルファPNGを必ずしも出力しない場合がある。プロンプトで「plain solid background(例: 単色グリーン/白)」を指定し、**後段で背景除去(クロマキー/`rembg`等)して透過PNG化**する工程を入れるのが堅実。アプリ側は最終的に透過PNGを要求(`§5.1`)。
- 1リクエストにつき**1キャラ・1感情**を生成し、構図を毎回固定する。
- 表情変更時は「change ONLY the facial expression」と**変えない箇所を明示**するのが効果的。

---

## 0. 設計方針(プロンプト構造)

立ち絵セットは「一貫性」が最重要。そのため、プロンプトを3ブロックに分離する。

```
[A] スタイル&構図ブロック   … 全感情で固定(画風・カメラ・ライティング)
[B] キャラクター定義ブロック … 容姿。後から差し替え可能(髪/目/服/体型/装飾)
[C] 表情ブロック            … 感情ごとに差し替える唯一の可変部分
```

最終プロンプト = **[A] + [B] + [C]**。
感情セットを作るときは **[A] と [B] を固定**し、**[C] だけ**を感情ラベルごとに入れ替える。

> 一貫性をさらに高めるには、画像生成AIで以下を併用する:
> - 同一 **seed**(固定)
> - **キャラクター参照**(IP-Adapter / reference-only / 同一LoRA / キャラ固定機能)
> - まず `neutral` を確定させ、それを参照画像として他感情を img2img / 表情編集で派生
> - 顔・髪・服の特徴語を全プロンプトで一字一句同じにする

---

## 1. [A] スタイル & 構図ブロック(全感情で固定)

英語プロンプト(SD系/多くの画像生成AIで安定)。日本語生成AIを使う場合は適宜翻訳。

```
masterplate, best quality, highly detailed anime style, visual novel CG, galge character art,
clean cel shading, soft lighting, vibrant colors,
upper body portrait, bust shot, head and shoulders to chest, centered composition,
character facing viewer, slight three-quarter view, looking at viewer,
solo, single character,
fully transparent background, alpha background, isolated character, no background, png with transparency,
consistent character design, sharp focus, studio lighting
```

ネガティブプロンプト(全感情共通):
```
lowres, bad anatomy, bad hands, extra fingers, missing fingers, extra limbs, deformed,
mutated, blurry, jpeg artifacts, watermark, signature, text, logo,
multiple characters, cropped head, out of frame, full body, lower body, legs,
background scenery, busy background, cluttered,
inconsistent style, off-model
```

固定パラメータ(目安):
- 解像度: 1024×1536(縦長バストアップ)
- seed: 固定値(例 `12345`)
- CFG / sampler / steps: セット内で固定

---

## 2. [B] キャラクター定義ブロック(容姿・後から差し替え)

> ここがユーザーが後で指示できる「容姿」部分。下記はテンプレートの**プレースホルダ例**。確定したら値を埋め、以後セット全体で固定する。

```
1girl, {age_look}, {hair_length} {hair_color} hair, {hairstyle},
{eye_color} eyes, {eye_shape},
{outfit}, {accessories},
{body_type}, {skin}, {distinctive_features}
```

### 2.1 変数の説明と記入例

| 変数 | 意味 | 記入例 |
|---|---|---|
| `{age_look}` | 見た目年齢の雰囲気 | `young woman, late teens look` |
| `{hair_color}` | 髪色 | `silver`, `light brown`, `pink` |
| `{hair_length}` | 髪の長さ | `long`, `medium`, `short` |
| `{hairstyle}` | 髪型 | `twin tails`, `straight hair with hime cut`, `wavy hair, side ponytail` |
| `{eye_color}` | 目の色 | `aqua blue`, `ruby red`, `golden` |
| `{eye_shape}` | 目の形 | `large round eyes`, `tareme (droopy eyes)`, `tsurime (sharp eyes)` |
| `{outfit}` | 服装 | `cute white blouse with ribbon`, `casual hoodie`, `school uniform` |
| `{accessories}` | 装飾品 | `hair ribbon, choker`, `hairpin, small earrings` |
| `{body_type}` | 体型 | `slim`, `petite` |
| `{skin}` | 肌 | `fair skin` |
| `{distinctive_features}` | 特徴 | `small mole under eye`, `ahoge (cowlick)` |

### 2.2 確定キャラクター: すみれ(Sumire)— **正典(canon)**

> `character/sumire/` の立ち絵セット(全14感情)で確定済みの容姿。容姿を再生成・修正する際はこの定義を固定して使う。

```
1girl, young woman with a teenage look,
long dark navy-black hair, low side braid over one shoulder with a white ribbon tie,
blue eyes, large gentle eyes,
cream-white blouse with a large lace-trimmed collar and small blue floral embroidery, pearl buttons,
pearl hair clip (cluster on bangs + small line down the braid),
slim figure, fair skin
```

特徴メモ: 編み込みは肩から前に流す。バストアップ構図。生成時の背景は**単色グリーン(クロマキー)**で、後段で背景除去して透過PNG化する(`§0-A`)。

> 別キャラに差し替える場合は、この `[B]` ブロックだけを差し替え、`[A]`(画風・構図)と `[C]`(表情)は固定する。

---

## 3. [C] 表情ブロック(感情ごとに差し替え)

各感情の差し替え句。`{emotion_id}` は [specification.md](specification.md) `§5.2` のラベルに対応(ファイル名にも使用)。

| `{emotion_id}` | 表情プロンプト([C] に入れる句) |
|---|---|
| `neutral` | `neutral expression, calm face, gentle closed-mouth, relaxed eyes, soft natural look` |
| `happy` | `happy expression, bright smile, open mouth smiling, sparkling eyes, cheerful, slight blush` |
| `smile` | `gentle soft smile, warm expression, closed mouth smile, kind eyes, serene` |
| `excited` | `excited expression, big open smile, wide sparkling eyes, energetic, raised eyebrows, blush of excitement` |
| `laugh` | `laughing happily, eyes closed in laughter, wide open mouth smile, joyful, hand near mouth` |
| `surprised` | `surprised expression, wide open eyes, raised eyebrows, slightly open mouth, startled look` |
| `sad` | `sad expression, downcast eyes, slight frown, teary eyes, gloomy, looking down a little` |
| `worried` | `worried expression, troubled look, furrowed brows, slight frown, uneasy eyes` |
| `angry` | `angry expression, pouting, furrowed brows, puffed cheeks, sharp eyes, slightly turned away` |
| `pout` | `pouting expression, sulky face, puffed cheeks, half-lidded annoyed eyes, looking aside` |
| `shy` | `shy embarrassed expression, heavy blush, looking away, small nervous smile, fidgeting` |
| `sleepy` | `sleepy expression, half-closed drowsy eyes, soft relaxed mouth, tired gentle look, slight yawn` |
| `thinking` | `thinking expression, looking up thoughtfully, finger on chin, slightly pursed lips, curious eyes` |
| `wink` | `playful wink, one eye closed, cheerful smile, tongue slightly out, lively expression` |

---

## 4. nano banana 用 自然言語プロンプト(正規)

### 4-A. 基準 `neutral` の生成(テキストのみ、参照画像なし)

```
Create a galge (Japanese visual novel) style character portrait.

Style: high-quality anime visual novel CG art, clean cel shading, soft studio lighting,
vibrant colors, sharp focus, consistent on-model character design.

Framing: upper-body bust shot — head, shoulders, and chest visible. Character centered,
facing the viewer in a slight three-quarter view, looking at the viewer. Single character only.

Character appearance:
{ここに §2.2 のキャラクター定義を自然文で記述。例:
A young woman with a teenage look, long silver hair in a side ponytail, large round
aqua-blue droopy eyes (tareme), wearing a cute off-white blouse with a soft blue ribbon
and a light cardigan, a small choker, fair skin, slim petite figure, with a small ahoge.}

Expression: neutral, calm and gentle, soft closed mouth, relaxed eyes.

Background: a plain solid flat background (single uniform color, e.g. chroma-key green),
no scenery, no props, so it can be cut out later.

Output: a single clean portrait, no text, no watermark.
```

→ 出力を背景除去して `assets/characters/aichan/neutral.png`(透過PNG)に保存。

### 4-B. 各感情の派生(参照画像 = `neutral.png` を渡す)

参照画像として `neutral.png` を添付したうえで、感情ごとに次の指示文を送る:

```
Using the attached character image as the exact reference, generate the SAME character
with ONLY the facial expression changed to: {§3 の感情プロンプト, 例: "happy — bright
open-mouth smile, sparkling eyes, cheerful, slight blush"}.

Keep EVERYTHING ELSE identical to the reference: same hairstyle and hair color, same face
shape and eye color, same outfit and accessories, same pose, same framing and composition,
same art style and lighting. Same plain solid background.

Do not change the character design. Change only the expression. Output one clean portrait,
no text, no watermark.
```

→ `{emotion}` を `§3` の各ラベルで差し替えて全感情を生成し、背景除去して `assets/characters/aichan/{emotion}.png` に保存。

> 下記 `§4` のタグ羅列方式([A]+[B]+[C])は、SD系を併用する場合や、各要素を確認するための**コンポーネント参照**として残す。nano banana では上記 4-A / 4-B を正とする。

---

## 4-tag. (参考)タグ羅列方式の組み立て例

`happy` を生成する場合(= [A] + [B] + [C:happy]):

```
masterplate, best quality, highly detailed anime style, visual novel CG, galge character art,
clean cel shading, soft lighting, vibrant colors,
upper body portrait, bust shot, head and shoulders to chest, centered composition,
character facing viewer, slight three-quarter view, looking at viewer,
solo, single character,
fully transparent background, alpha background, isolated character, no background, png with transparency,
consistent character design, sharp focus, studio lighting,

1girl, young woman with a teenage look, long silver hair, straight hair with side ponytail,
aqua blue eyes, large round tareme eyes,
cute off-white blouse with a soft blue ribbon, light cardigan,
hair ribbon, small choker, slim petite figure, fair skin, small ahoge,

happy expression, bright smile, open mouth smiling, sparkling eyes, cheerful, slight blush
```

→ 出力を `assets/characters/aichan/happy.png`(透過PNG)として保存。
全感情について [C] だけ差し替えて繰り返す。

---

## 5. 一貫性チェックリスト

立ち絵セット完成後、以下を確認:
- [ ] 全画像で**髪型・髪色・目の色・服**が一致しているか(同一キャラに見えるか)
- [ ] **構図(顔の大きさ・位置・カメラ角度)**が揃っているか(差し替え時にガタつかないか)
- [ ] **背景が完全透過**か(縁の白フチ・残りがないか)
- [ ] 画風(線・塗り)がブレていないか
- [ ] 表情がラベルの感情と一致しているか
- [ ] サイズ・アスペクト比が統一されているか

ズレが出た感情は、`neutral` を参照画像にした **img2img / 表情のみ編集** で作り直すと揃いやすい。

---

## 6. 容姿変更の運用(後からの指示に対応)

要件「容姿は後々指示に追加できるように」への対応手順:
1. ユーザーが容姿の希望(髪色・服など)を指示。
2. **[B] キャラクター定義ブロックの変数のみ**を更新。[A]・[C]は触らない。
3. 同一 seed / 同一参照で**全感情を再生成**(セット一括更新)。
4. `assets/characters/{新character_id}/` に保存し、設定の `character_id` を切替。

> [A](画風・構図)と [C](表情)を固定したまま [B] だけ変えることで、容姿変更後も**感情表現と画風の一貫性**を保てる。
