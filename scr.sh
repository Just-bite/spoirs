#!/bin/bash

git pull

rm -f f.zip

# Run the client script with predefined commands
python LAB_1/client.py << EOF
192.168.84.99
download f.zip
exit
EOF

# Calculate and display the SHA256 checksum of the downloaded file
sha256sum f.zip
rm -f f.zip

# Run the client script with predefined commands
python LAB_2/client.py << EOF
192.168.84.99
9091
download f.zip
exit
EOF

# Calculate and display the SHA256 checksum of the downloaded file
sha256sum f.zip