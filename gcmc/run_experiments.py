import os

dropout_rates = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

for input_rate in dropout_rates:
    for rate in dropout_rates:
        os.system("python train.py -d ml_100k --accum stack -ido {} -do {} -nleft -nb 2 -e 1000 -wf --testing".format(input_rate,rate))