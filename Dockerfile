FROM node:18-alpine

WORKDIR /

COPY . /

RUN npm install

EXPOSE 3000

CMD ["node", "app.js"]

# FROM node:18-alpine

# RUN mkdir -p /home/user-auth-service

# COPY . /home/user-auth-service

# WORKDIR /home/user-auth-service

# RUN npm install

# EXPOSE 9602

# CMD [ "node", "app.js"]