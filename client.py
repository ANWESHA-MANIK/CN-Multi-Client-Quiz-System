import socket

SERVER_IP = "127.0.0.1"   
PORT = 5000

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((SERVER_IP, PORT))

print("Connected to Quiz Server")


name = input("Enter your name: ")
client.send(name.encode())

while True:
    try:
        
        question = client.recv(1024).decode()

        if not question:
            break

        
        if "Your Score" in question:
            print(question)
            break

        print("\nQuestion:", question)

        
        answer = input("Your Answer: ")
        client.send(answer.encode())

    except:
        break

client.close()
print("Connection closed")