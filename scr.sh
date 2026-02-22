#!/bin/bash

git pull

rm -f f.zip

echo l_1 

python LAB_1/client.py << EOF
192.168.84.99
9090
download f.zip
exit
EOF

sha256sum f.zip
rm -f f.zip

echo l_2 

python LAB_2/client.py << EOF
192.168.84.99
9091
download f.zip
exit
EOF

# Calculate and display the SHA256 checksum of the downloaded file
sha256sum f.zip