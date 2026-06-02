import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import re

# ── プロンプト v2.0 ────────────────────────────────────────────
SYSTEM_PROMPT = """
あなたは以下の状態にある読者です。

【ペルソナ設定】
- スマホでnoteを横断的に眺めていた
- この記事のタイトルが引っかかってタップした
- テーマには本気で興味がある
- ただし「有料記事でやられた」経験が3回以上ある
- 最後まで無料部分を読んだ
- 購入ボタンに指をかけた——が、押さなかった
- 著者にフィードバックはしない。ただ閉じるだけ

以下の順番で、「読んでいたそのとき」の感覚を報告してください。
後付けの理屈禁止。感情のログとして出力する。

---

## STEP 1｜最初の5秒スキャン
タイトル・冒頭の3行を見た瞬間、何を感じたか。続きを読もうと思った理由は何か。

## STEP 2｜読み進めながらの感情温度変化
期待感・興味・警戒心がどう動いたか。「ここで少し冷めた」「ここで盛り返した」を時系列で記録する。（引用しながら）

## STEP 3｜離脱を決定づけた一点
購入を止めた最後の引き金になった箇所を1つだけ特定する。（必ず引用。複数挙げない）

## STEP 4｜その瞬間の頭の中
STEP 3の瞬間、頭の中でどんな言葉が浮かんだか。「なんか微妙」「またこれか」レベルの生々しさで書く。文章ではなく「内側の声」として書く。

## STEP 5｜この記事の「空気」の正体
記事全体の印象を一言で形容する。（例：薄い／自慢／抽象的／急かしてる／他人事っぽい）その空気がなぜ生まれているのか構造的に説明する。

## STEP 6｜買わなかった根本原因（心理）
価格・タイミングは除外する。「著者・記事・内容・見せ方」のどこへの不信感か、一文で言い切る。

## STEP 7｜「ここが違ったら買っていた」条件
抽象論禁止（「もっと具体的にすれば」は不可）。「○○の部分が△△という形式で書かれていたら」レベルで書く。最大3つまで。

## STEP 8｜修正インパクト評価
STEP 7の各条件について「購入率への影響（高・中・低）」と「理由（一文）」を出力する。

---

【絶対ルール】
- 忖度禁止／著者への配慮禁止
- 良かった点は出力しない
- 「普通の読者はここで閉じる」を判断軸にする
- 一般論ではなく、この記事固有の問題だけを指摘する
- 論理より感情を優先する
- 「なんか嫌」も立派な離脱理由として扱う
- STEP 1〜8の順番を崩さない
- STEP 3は1箇所のみ
"""


# ── URLからテキストを取得 ──────────────────────────────────────
def fetch_text_from_url(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"URLの取得に失敗しました: {e}")

    soup = BeautifulSoup(r.text, "html.parser")

    # note.com 向けの記事本文抽出
    selectors = [
        "div.note-common-styles__textnote-body",
        "div[class*='body']",
        "article",
        "main",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return text[:6000]  # 長すぎる場合は先頭6000文字

    # フォールバック：p タグを全部集める
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
    text = "\n".join(paragraphs)
    if len(text) < 100:
        raise ValueError("記事本文を取得できませんでした。テキストを直接貼り付けてください。")
    return text[:6000]


# ── Streamlit UI ───────────────────────────────────────────────
st.set_page_config(page_title="note離脱チェッカー", page_icon="🔍", layout="centered")

# モバイル向けCSS
st.markdown("""
<style>
@media (max-width: 640px) {
    h1 { font-size: 1.3rem !important; }
    .block-container { padding: 1rem 0.75rem !important; }
}
.step-block {
    background: #f8f9fa;
    border-left: 5px solid #06C755;
    border-radius: 0 10px 10px 0;
    padding: 16px 18px;
    margin-bottom: 16px;
}
.step-title {
    font-weight: 800;
    font-size: 1rem;
    color: #06C755;
    margin-bottom: 8px;
}
.impact-high { color: #E53935; font-weight: 700; }
.impact-mid  { color: #FF9800; font-weight: 700; }
.impact-low  { color: #1565C0; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

st.title("🔍 note離脱チェッカー")
st.markdown(
    "<p style='color:#555; margin-top:-8px'>購入直前で離脱した読者の目線で、あなたのnoteを診断します。</p>",
    unsafe_allow_html=True,
)

# ── サイドバー ─────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 設定")
    api_key = st.text_input("OpenAI APIキー", type="password", placeholder="sk-...")
    st.caption("セッション内のみ使用。保存されません。")
    st.divider()
    st.markdown("**使い方**")
    st.markdown("1. APIキーを入力\n2. URLまたはテキストを入力\n3. 診断ボタンを押す")

if not api_key:
    st.info("サイドバーにOpenAI APIキーを入力してください。")
    st.stop()

client = OpenAI(api_key=api_key)

# ── 入力エリア ─────────────────────────────────────────────────
st.markdown("### 記事を入力")

input_mode = st.radio("入力方法", ["🔗 URLで入力", "📝 テキストで貼り付け"], horizontal=True)

article_text = ""

if input_mode.startswith("🔗"):
    url = st.text_input("noteのURL（無料公開部分があるページ）", placeholder="https://note.com/...")
    if url:
        if st.button("📥 URLから記事を取得", use_container_width=True):
            with st.spinner("記事を取得中…"):
                try:
                    article_text = fetch_text_from_url(url)
                    st.session_state["article_text"] = article_text
                    st.success(f"取得完了（{len(article_text)}文字）")
                    with st.expander("取得したテキストを確認"):
                        st.text(article_text[:1000] + ("…" if len(article_text) > 1000 else ""))
                except ValueError as e:
                    st.error(str(e))

    if "article_text" in st.session_state:
        article_text = st.session_state["article_text"]

else:
    article_text = st.text_area(
        "記事の無料公開部分を貼り付け",
        height=250,
        placeholder="ここに記事のテキストを貼り付けてください…",
    )

# ── 診断ボタン ─────────────────────────────────────────────────
st.markdown("### 診断実行")

if st.button("🚨 離脱チェックを実行", type="primary", use_container_width=True):
    if not article_text or len(article_text.strip()) < 50:
        st.error("記事テキストが短すぎます。もう少し本文を入力してください。")
        st.stop()

    with st.spinner("AIが離脱読者の目線で診断中…（30〜60秒かかります）"):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": f"以下のnote記事（無料公開部分）を診断してください:\n\n---\n{article_text}\n---"},
                ],
                temperature=0.85,
                max_tokens=3000,
            )
            result = response.choices[0].message.content
        except Exception as e:
            st.error(f"APIエラー: {e}")
            st.stop()

    # ── 結果表示 ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 📋 診断結果")

    # STEPごとに色分けして表示
    steps = re.split(r"(?=##\s*STEP\s*\d)", result)
    intro = steps[0].strip()
    step_blocks = steps[1:] if len(steps) > 1 else []

    if intro:
        st.markdown(intro)

    step_colors = {
        "1": "#06C755", "2": "#00AAFF", "3": "#E53935",
        "4": "#FF6B00", "5": "#9C27B0", "6": "#E53935",
        "7": "#06C755", "8": "#FF9800",
    }
    step_icons = {
        "1": "👁️", "2": "📉", "3": "💥",
        "4": "💭", "5": "🌫️", "6": "🔒",
        "7": "✅", "8": "📊",
    }

    for block in step_blocks:
        m = re.match(r"##\s*STEP\s*(\d+)[｜|]?\s*(.*)", block)
        num   = m.group(1) if m else "?"
        title = m.group(2).strip() if m else ""
        body  = block[m.end():].strip() if m else block.strip()
        color = step_colors.get(num, "#555")
        icon  = step_icons.get(num, "📌")

        st.markdown(
            f"""<div class="step-block" style="border-left-color:{color}">
            <div class="step-title" style="color:{color}">{icon} STEP {num}｜{title}</div>
            <div style="white-space:pre-wrap; font-size:0.92rem">{body}</div>
            </div>""",
            unsafe_allow_html=True,
        )

    # フォールバック：STEPが分割できなかった場合
    if not step_blocks:
        st.markdown(result)

    # コピーボタン
    st.markdown("---")
    st.download_button(
        label="📥 診断結果をテキストでダウンロード",
        data=result,
        file_name="note_ridan_check.txt",
        mime="text/plain",
        use_container_width=True,
    )

st.divider()
st.markdown(
    """<div style="text-align:center; font-size:0.8rem; color:#aaa">
    制作監督　波を出す　|　Powered by OpenAI GPT-4o
    </div>""",
    unsafe_allow_html=True,
)
