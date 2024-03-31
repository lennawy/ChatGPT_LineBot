# Import Packages
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage,
                            ImageSendMessage, AudioMessage)
import os
import uuid
import random
from src.models import OpenAIModel
from src.memory import Memory
from src.logger import logger
from src.storage import Storage, FileStorage, MongoStorage
from src.utils import get_role_and_content
from src.service.youtube import Youtube, YoutubeTranscriptReader
from src.service.website import Website, WebsiteReader
from src.mongodb import mongodb
from linebot.models import PostbackAction, URIAction, MessageAction, TemplateSendMessage, ButtonsTemplate

load_dotenv('.env')

# 輸入 LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET 串接 Line Bot, 金鑰存在 Replit Secrets
# memory 儲存對話
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
storage = None
youtube = Youtube(step=4)
website = Website()

memory = Memory(system_message=os.getenv('SYSTEM_MESSAGE'),
                memory_message_count=2)
model_management = {}
api_keys = {}

# 收到 POST request 時, 用 callback 函式處理
# LINE_CHANNEL_SECRET 等金鑰不正確時的報錯訊息
@app.route("/callback", methods=['POST'])
def callback():
  signature = request.headers['X-Line-Signature']
  body = request.get_data(as_text=True)
  app.logger.info("Request body: " + body)
  try:
    handler.handle(body, signature)
  except InvalidSignatureError:
    print(
      "Invalid signature. Please check your channel access token/channel secret."
    )
    abort(400)
  return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
  #這邊加入判斷關鍵字不同的 case
  case1 = [
    '痛苦', '傷心', '難過', '撐不下去', '扛不住', 'emo', 'depressed', 'sad', '心情糟', '煩',
    '心情差', '心情不好', '憂鬱', '煎熬', '累', '放棄'
  ]
  case2 = [
    '考不好', '考差', '考爛', '成績差', '成績爛', '分數低', '功課多', '報告多', '課好難', '課好多', '功課好多',
    '作業好多', '報告好多', '考試好多', '期中地獄', '期末地獄'
  ]
  case3 = ['分手','跟男友吵架', '跟女友吵架','失戀']
  case4 = ['沒錢', '月底了', '薪水很低', '學貸還不出來', '學費', '生活費好高', '房租好高', '存款好少', '經濟壓力大']
  prob = random.random()
  add_msg = ''
  count1 = count2 = count3 = count4 = False
  #結束
  user_id = event.source.user_id
  text = event.message.text.strip()
  logger.info(f'{user_id}: {text}')
  
  try:
    #加入關鍵字偵測觸發信件
    for c in case1 :
      if c in text:
        count1 = True
        break
    for c in case2 :
      if c in text:
        count2 = True
        break
    for c in case3:
      if c in text:
        count3 = True
        break
    for c in case4:
      if c in text:
        count4 = True
        break
    if prob <= 0.4:
      if count1 == True:
        add_msg = "你最近的心情似乎不是很好，有人給你寫了封信喔：      https://drive.google.com/file/d/14FZE5pJFe7oJ6m48_4M5ETcJ_DCa6BW5/view?usp=sharing"
      elif count2 == True:
        add_msg ="我知道學校的各種事都蠻煩人的，看起來某人也有同感：https://drive.google.com/file/d/1Acw6cnb1guGkanS7THHGvfvK-gF5dSK7/view?usp=sharing"
      elif count3 == True:
        add_msg = '你好像有一些困擾喔！有人給你寫了封信喔：https://drive.google.com/file/d/1xt4YTtofPsJLx5MgaZTWhH83OycPoA_A/view?usp=sharing'
      elif count4 == True:
        add_msg = '你好像有一些困擾喔！有人給你寫了封信喔：https://drive.google.com/file/d/1mAXgKIatF0yg69PgsXWDNDX6nmghVAih/view?usp=share_link'
    # end
    
    # 偵測 API Token 是否有效    
    if text.startswith('/註冊'):
      api_key = text[3:].strip()
      model = OpenAIModel(api_key=api_key)
      is_successful, _, _ = model.check_token_valid()
      if not is_successful:
        raise ValueError('Invalid API token')
      model_management[user_id] = model
      storage.save({user_id: api_key})
      msg = TextSendMessage(text='Token 有效，註冊成功')
      
    # 指令介紹     
    elif text.startswith('/指令說明'):
      msg = TextSendMessage(
        text=
        "指令：\n/註冊 + API Token\n👉 API Token 請先到 https://platform.openai.com/ 註冊登入後取得\n\n/系統訊息 + Prompt\n👉 Prompt 可以命令機器人扮演某個角色，例如：請你扮演擅長做總結的人\n\n/清除\n👉 當前每一次都會紀錄最後兩筆歷史紀錄，這個指令能夠清除歷史訊息\n\n/圖像 + Prompt\n👉 會調用 DALL∙E 2 Model，以文字生成圖像\n\n語音輸入\n👉 會調用 Whisper 模型，先將語音轉換成文字，再調用 ChatGPT 以文字回覆\n\n其他文字輸入\n👉 調用 ChatGPT 以文字回覆"
      )

    elif text.startswith('/系統訊息'):
      memory.change_system_message(user_id, text[5:].strip())
      msg = TextSendMessage(text='輸入成功')
      
    # 針對 ChatGPT 無法正確提供某些主題資訊, 若使用者輸入特定 prompt 則直接產生回應
    # 搭配 Line Developers 圖文面板使用, 點選特定圖文面板後會自動幫使用者打出 prompt 
    # 心理諮商資源
    elif text.startswith('政大附近的心理諮商診所有哪些？'):
      msg = TextSendMessage(
        text=
        '1. 政大心理諮商中心，是離學校最近的選擇，人潮有點多需要提前預約，地址是：台北市文山區新光路一段25巷29號\n\n
        2. 木柵身心診所，搭530號公車大約15分鐘，大多數人對診所的評價是親切且專業，地址是：台北市文山區辛亥路四段246號\n\n
        3. 利伯他茲心理諮商所，搭933號公車大約10分鐘，評論數不多但評價良好，地址是台北市文山區木柵路二段62號2樓\n\n
        4. 依懷心理諮商所，搭棕6號公車大約20分鐘，聽說環境讓人很放鬆，地址是：台北市文山區羅斯福路六段297號6樓\n\n
        5. 羅吉斯心理諮商所，搭棕6號公車大約20分鐘，部分民眾對諮商師評價是專業，但也有部分的人認為遭受批評，地址是：台北市文山區景興路258號'
      )
      
    # 散心地點推薦    
    elif text.startswith('政大附近散心地點推薦？'):
      msg = TextSendMessage(
        text=
        '1. 小坑溪文學步道，寧靜悠閒自在的步道，可搭乘棕11至政大二街站下車，約30分鐘可以走完\n\n
        2. 清溪綠地，鄰近政大，景緻優美，適合一個小時的散步\n\n
        3. 道南河濱公園，景美溪岸的河濱公園，公園除了具備運動設施外，還有相當有特色的兒遊戲場\n\n
        4. 福德坑滑草場，不用自備滑草板，現場有五台滑草車供大家使用，可以玩的非常盡興，適合一大早來\n\n
        5. 貓空壺穴，可以搭乘纜車到貓空站再步行過來，約20多分鐘，壺穴吊橋小巧可愛，容易濕滑要小心不要滑倒！'
      )

    elif text.startswith('/清除'):
      memory.remove(user_id)
      msg = TextSendMessage(text='歷史訊息清除成功')

    elif text.startswith('/圖像'):
      prompt = text[3:].strip()
      memory.append(user_id, 'user', prompt)
      is_successful, response, error_message = model_management[
        user_id].image_generations(prompt)
      if not is_successful:
        raise Exception(error_message)
      url = response['data'][0]['url']
      msg = ImageSendMessage(original_content_url=url, preview_image_url=url)
      memory.append(user_id, 'assistant', url)

    else:
      user_model = model_management[user_id]
      memory.append(user_id, 'user', text)
      url = website.get_url_from_text(text)
      if url:
        if youtube.retrieve_video_id(text):
          is_successful, chunks, error_message = youtube.get_transcript_chunks(
            youtube.retrieve_video_id(text))
          if not is_successful:
            raise Exception(error_message)
          youtube_transcript_reader = YoutubeTranscriptReader(
            user_model, os.getenv('OPENAI_MODEL_ENGINE'))
          is_successful, response, error_message = youtube_transcript_reader.summarize(
            chunks)
          if not is_successful:
            raise Exception(error_message)
          role, response = get_role_and_content(response)
          msg = TextSendMessage(text=response)
        else:
          chunks = website.get_content_from_url(url)
          if len(chunks) == 0:
            raise Exception('無法撈取此網站文字')
          website_reader = WebsiteReader(user_model,
                                         os.getenv('OPENAI_MODEL_ENGINE'))
          is_successful, response, error_message = website_reader.summarize(
            chunks)
          if not is_successful:
            raise Exception(error_message)
          role, response = get_role_and_content(response)
          msg = TextSendMessage(text=response)
      else:
        is_successful, response, error_message = user_model.chat_completions(
          memory.get(user_id), os.getenv('OPENAI_MODEL_ENGINE'))
        if not is_successful:
          raise Exception(error_message)
        role, response = get_role_and_content(response)
        #增加add_msg
        msg = TextSendMessage(text=response+add_msg)
      memory.append(user_id, role, response)
  except ValueError:
    msg = TextSendMessage(text='Token 無效，請重新註冊，格式為 /註冊 sk-xxxxx')
  except KeyError:
    msg = TextSendMessage(text='請先註冊 Token，格式為 /註冊 sk-xxxxx')
  except Exception as e:
    memory.remove(user_id)
    if str(e).startswith('Incorrect API key provided'):
      msg = TextSendMessage(text='OpenAI API Token 有誤，請重新註冊。')
    elif str(e).startswith(
        'That model is currently overloaded with other requests.'):
      msg = TextSendMessage(text='已超過負荷，請稍後再試')
    else:
      msg = TextSendMessage(text=str(e))
  line_bot_api.reply_message(event.reply_token, msg)


@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event):
  user_id = event.source.user_id
  audio_content = line_bot_api.get_message_content(event.message.id)
  input_audio_path = f'{str(uuid.uuid4())}.m4a'
  with open(input_audio_path, 'wb') as fd:
    for chunk in audio_content.iter_content():
      fd.write(chunk)

  try:
    if not model_management.get(user_id):
      raise ValueError('Invalid API token')
    else:
      is_successful, response, error_message = model_management[
        user_id].audio_transcriptions(input_audio_path, 'whisper-1')
      if not is_successful:
        raise Exception(error_message)
      memory.append(user_id, 'user', response['text'])
      is_successful, response, error_message = model_management[
        user_id].chat_completions(memory.get(user_id), 'gpt-3.5-turbo')
      if not is_successful:
        raise Exception(error_message)
      role, response = get_role_and_content(response)
      memory.append(user_id, role, response)
      msg = TextSendMessage(text=response)
  except ValueError:
    msg = TextSendMessage(text='請先註冊你的 API Token，格式為 /註冊 [API TOKEN]')
  except KeyError:
    msg = TextSendMessage(text='請先註冊 Token，格式為 /註冊 sk-xxxxx')
  except Exception as e:
    memory.remove(user_id)
    if str(e).startswith('Incorrect API key provided'):
      msg = TextSendMessage(text='OpenAI API Token 有誤，請重新註冊。')
    else:
      msg = TextSendMessage(text=str(e))
  os.remove(input_audio_path)
  line_bot_api.reply_message(event.reply_token, msg)


@app.route("/", methods=['GET'])
def home():
  return 'Hello World'


if __name__ == "__main__":
  if os.getenv('USE_MONGO'):
    mongodb.connect_to_database()
    storage = Storage(MongoStorage(mongodb.db))
  else:
    storage = Storage(FileStorage('db.json'))
  try:
    data = storage.load()
    for user_id in data.keys():
      model_management[user_id] = OpenAIModel(api_key=data[user_id])
  except FileNotFoundError:
    pass
  app.run(host='0.0.0.0', port=8080)
  
  
  
