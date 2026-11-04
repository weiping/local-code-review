#!/bin/sh
# Build the demo repository: a clean commit, then five planted bugs left uncommitted in the working tree,
# plus a renamed file, a 300 KB data file with a one-line change, and an untracked new file.
set -eu
dest=${1:?usage: make_repo.sh DIR}
here=$(cd "$(dirname "$0")" && pwd)
rm -rf "$dest" && mkdir -p "$dest" && cd "$dest"
git init -q -b main
git config user.email demo@example.com && git config user.name demo
mkdir -p app tests data && touch app/__init__.py tests/__init__.py
cp "$here/orders_clean.py" app/orders.py
cp "$here/test_orders.py" tests/test_orders.py
printf 'def money(cents):\n    return f"{cents / 100:.2f}"\n' > app/util.py
python3 -c "
import random; random.seed(7)
with open('data/catalog.txt','w') as f:
    for i in range(9000): f.write(f'sku-{i:05d},{random.randint(100,99999)},item number {i}\n')"
git add . && git commit -qm "orders module"
# the change under review
cp "$here/orders_buggy.py" app/orders.py
git mv app/util.py app/helpers.py
printf 'def money(cents):\n    return f"{cents / 100:.2f}"\n\ndef percent(x):\n    return f"{x:.1%%}"\n' > app/helpers.py
# portable in-place edit (BSD sed on macOS has no plain -i)
sed 's/^sku-00042,.*/sku-00042,1999,item number 42 (repriced)/' data/catalog.txt > data/catalog.new && mv data/catalog.new data/catalog.txt
printf 'from app.orders import revenue\n\ndef summary(orders):\n    return {"revenue": revenue(orders)}\n' > app/report.py
echo "demo repo ready in $dest"
