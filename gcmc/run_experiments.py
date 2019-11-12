import os
from datetime import datetime

def grid_search():
    #input_rates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    #dropout_rates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    input_rates = [0.3, 0.4, 0.5]
    dropout_rates = [0.7]

    out_file_name = '2019-11-11.txt'
    itr_times = 5

    with open(out_file_name,'a') as f:
        f.write('{}\n'.format(datetime.now()))
    for input_rate in input_rates:
        for rate in dropout_rates:
            for i in range(1,itr_times+1):
                with open(out_file_name,'a') as f:
                    f.write('Input dropout rate: {}, dropout rate: {}\nIteration {}\n'.format(input_rate,rate,i)) 
                os.system("python train.py -d ml_100k --accum stack -ido {} -do {} -nleft -nb 2 -e 1000 -wf {} --testing -attn".format(input_rate,rate,out_file_name))

def individual_experiments():
    dropouts = []


def main():
    grid_search()
    #individual_experiments()

if __name__ == "__main__":
    main()
    