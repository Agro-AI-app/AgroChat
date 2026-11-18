import os

import uvicorn


if __name__ == '__main__':
    uvicorn.run('agrochat.app:app', host=os.getenv('AGROCHAT_HOST', '127.0.0.1'),
                port=int(os.getenv('PORT', '8080')), workers=1)
