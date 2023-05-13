# Latent Flow Matching

Updates:
[x] Support Classifier-free guidance for Karras Euler sampler

[x] Support Karras Heun sampler (to use, pls set args.method == "stochastic")

[x] Support Karras Euler sampler (to use, pls set args.method == "euler")

[x] Support DiT for unconditional

[x] Support class conditional for ImageNet (both EDM and DiT)

[x] Correct notation for flow matching: 1 - random noise, 0 - real data

## Installation
Python 3.10.11 and Pytorch 1.13.1 are used in this implementation.
Please install required libraries:
```
pip install -r requirements.txt
```
Install nvidia cuda in conda env:
```
conda install -c nvidia cuda
```

## Training
All training scripts are wrapped in `run.sh`. Simply comment/uncomment the relevant commands and run `bash run.sh`.

## Testing
Some pieces of test scripts are included in `run_test.sh`. Following the same procedure as [training above](#training).

For massive testing on various epochs, please first modify some arguments in [test_laflo_slurm.py](./test_laflo_slurm.py) and then run `python test_laflo_slurm.py` to automatically generate bash script.


