import torch
import torch.distributed as dist
import collections
import inspect
from colossalai.tensor import ColoTensor


def filter_dict(dict_to_filter, thing_with_kwargs):
    sig = inspect.signature(thing_with_kwargs)
    filter_keys = [param.name for param in sig.parameters.values() if param.kind == param.POSITIONAL_OR_KEYWORD]
    filter_dict = {}
    for filter_key in filter_keys:
        if filter_key in dict_to_filter:
            filter_dict[filter_key] = dict_to_filter[filter_key]
    return filter_dict


def save_checkpoint(dire: str,
                    epoch: int,
                    model: torch.nn.Module,
                    optimizer: torch.optim.Optimizer = None,
                    lr_scheduler: torch.optim.lr_scheduler._LRScheduler = None,
                    *args,
                    **kwargs):
    """save_checkpoint 
    save a model, whose parameters are `ColoTensor`s.
    Args:
        dire (str): directory to save the checkpoint files.
        epoch (int): the number of epoch
        model (torch.nn.Module): a torch module initialized by ColoInitContext
        optimizer (torch.optim.Optimizer, optional): optimizers. Defaults to None.
        lr_scheduler (torch.optim.lr_scheduler._LRScheduler, optional): lr schedule. Defaults to None.
    """
    model_state = {'epoch': epoch, 'model': model.state_dict()}

    mapping = dict()
    for p in model.parameters():
        if isinstance(p, ColoTensor):
            mapping[id(p)] = (p.dist_spec, p.compute_spec)
            p.to_replicate()

    if dist.get_rank() == 0:
        torch.save(model_state, dire + '/epoch_{}_model.pth'.format(epoch))

    for p in model.parameters():
        if isinstance(p, ColoTensor):
            p.set_tensor_spec(*mapping[id(p)])

    optim_state = {'epoch': epoch, 'optimizer': optimizer.state_dict(), 'lr_scheduler': lr_scheduler.state_dict()}

    mapping = dict()
    for p, v in optimizer.state.items():
        if isinstance(p, ColoTensor):
            mapping[id(p)] = (p.dist_spec, p.compute_spec)
            p = p.to_replicate()

    if dist.get_rank() == 0:
        torch.save(optim_state, dire + '/epoch_{}_optim.pth'.format(epoch))

    for p, v in optimizer.state.items():
        if isinstance(p, ColoTensor):
            p = p.set_tensor_spec(*mapping[id(p)])


def load_checkpoint(dire,
                    epoch: int,
                    rank: int,
                    model: torch.nn.Module,
                    optimizer: torch.optim.Optimizer = None,
                    lr_scheduler: torch.optim.lr_scheduler._LRScheduler = None,
                    *args,
                    **kwargs):
    """load_checkpoint 
    load a model, whose parameters are `ColoTensor`s.
    Args:
        dire (_type_): _description_
        epoch (int): _description_
        rank (int): _description_
        model (torch.nn.Module): _description_
        optimizer (torch.optim.Optimizer, optional): _description_. Defaults to None.
        lr_scheduler (torch.optim.lr_scheduler._LRScheduler, optional): _description_. Defaults to None.
    """
    model_state = torch.load(dire + '/epoch_{}_model.pth'.format(epoch))
    model_state['model'] = collections.OrderedDict([(k.split('.', 1)[1], v) for k, v in model_state['model'].items()])

    mapping = dict()
    for p in model.parameters():
        if isinstance(p, ColoTensor):
            mapping[id(p)] = (p.dist_spec, p.compute_spec)
            p.to_replicate()

    model.load_state_dict(model_state['model'])

    for p in model.parameters():
        if isinstance(p, ColoTensor):
            p.set_tensor_spec(*mapping[id(p)])

    mapping = dict()
    for p, v in optimizer.state.items():
        if isinstance(p, ColoTensor):
            mapping[id(p)] = (p.dist_spec, p.compute_spec)
            p = p.to_replicate()

    optim_state = torch.load(dire + '/epoch_{}_optim.pth'.format(epoch))
    optimizer.load_state_dict(optim_state['optimizer'])

    for p, v in optimizer.state.items():
        if isinstance(p, ColoTensor):
            p = p.set_tensor_spec(*mapping[id(p)])

    lr_scheduler_dict = optim_state['lr_scheduler']
    if 'after_scheduler_type' in lr_scheduler_dict:
        after_scheduler_type = lr_scheduler_dict.pop('after_scheduler_type')
        after_scheduler_dict = lr_scheduler_dict.pop('after_scheduler_dict')
        reload_scheduler = getattr(torch.optim.lr_scheduler, after_scheduler_type)
        filtered_dict = filter_dict(after_scheduler_dict, reload_scheduler)
        lr_scheduler_dict['after_scheduler'] = reload_scheduler(
            optimizer,
            **filtered_dict,
        )
    lr_scheduler.load_state_dict(lr_scheduler_dict)