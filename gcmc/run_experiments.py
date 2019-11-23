import os
from datetime import datetime

out_file_name = '2019-11-22.txt'
itr_times = 5
accum = 'stack' # sum or stack

def grid_search():
    input_rates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    dropout_rates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    #input_rates = [0.4, 0.5, 0.6, 0.7, 0.8]
    #dropout_rates = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    with open(out_file_name,'a') as f:
        f.write('{}\n'.format(datetime.now()))
    for input_rate in input_rates:
        for rate in dropout_rates:
            with open(out_file_name,'a') as f:
                f.write('Input dropout rate: {}, dropout rate: {}, average of {} experiments\n'.format(input_rate,rate,itr_times)) 
            os.system("python train.py -d ml_100k --accum {} -ido {} -do {} -nleft -nb 2 -e 1000 -wf {} --testing -attn -ne {}".format(accum,input_rate,rate,out_file_name,itr_times))

def individual_experiments():
    #dropouts = [(0.4,0.6),(0.5,0.4),(0.5,0.5),(0.5,0.7)]
    dropouts = [(0.2,0.8)]

    with open(out_file_name,'a') as f:
        f.write('{}\n'.format(datetime.now()))
    for i,j in dropouts:
        with open(out_file_name,'a') as f:
            f.write('Input dropout rate: {}, dropout rate: {}, average of {} experiments\n'.format(i,j,itr_times)) 
        os.system("python train.py -d ml_100k --accum {} -ido {} -do {} -nleft -nb 2 -e 1000 -wf {} --testing -attn -ne {}".format(accum,i,j,out_file_name,itr_times))

def main():
    grid_search()
    #individual_experiments()

if __name__ == "__main__":
    main()
    