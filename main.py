# -*- coding: utf-8 -*-
from utils.client import BotPool

pool = BotPool()

pool.setup()

import os
from keep_alive import keep_alive
keep_alive()
bot = Bot(token=os.environ.get(''))
client.run(token)
