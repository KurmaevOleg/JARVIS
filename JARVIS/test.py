import requests

url = "https://api.intelligence.io.solutions/api/v1/chat/completions"

headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer io-v2-eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJvd25lciI6IjA4ZjI3MDhhLWNlZGItNGJjYy1iYjc"
                     "0LTg3Nzk4ZmZlNjkxMCIsImV4cCI6NDkwNjc2Mjg0NX0.lZsysp2ZNYAdV1htzfWnX-8uef5HGi7Z_qlzEVsPLxFvvj7i"
                     "9oVpy3-o0pXGGtZLFYf-41kfv78g6UTDNkFSow"
}

data = {
    "model": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    "messages": [
        {
            "role": "system",
            "content": "You are a helpful assistant. Be brief"
        },
        {
            "role": "user",
            "content": "Hello!"
        }
    ]
}

response = requests.post(url, headers=headers, json=data)

print(response.json())
