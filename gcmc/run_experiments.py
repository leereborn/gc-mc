import os
from datetime import datetime

input_rates = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
dropout_rates = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

with open('results.txt','a') as f:
    f.write('{}\n'.format(datetime.now()))
for input_rate in input_rates:
    for rate in dropout_rates:
        with open('results.txt','a') as f:
            f.write('Input dropout rate: {}, dropout rate: {}\n'.format(input_rate,rate)) 
        os.system("python train.py -d ml_100k --accum stack -ido {} -do {} -nleft -nb 2 -e 1000 -wf --testing".format(input_rate,rate))