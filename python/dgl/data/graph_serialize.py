"""For Graph Serialization"""
from __future__ import absolute_import
import os
from ..graph import DGLGraph
from ..heterograph import DGLHeteroGraph
from .._ffi.object import ObjectBase, register_object
from .._ffi.function import _init_api
from .. import backend as F
from .heterograph_serialize import HeteroGraphData, save_heterographs

_init_api("dgl.data.graph_serialize")

__all__ = ['save_graphs', "load_graphs", "load_labels"]


@register_object("graph_serialize.StorageMetaData")
class StorageMetaData(ObjectBase):
    """StorageMetaData Object
    attributes available:
      num_graph [int]: return numbers of graphs
      nodes_num_list Value of NDArray: return number of nodes for each graph
      edges_num_list Value of NDArray: return number of edges for each graph
      labels [dict of backend tensors]: return dict of labels
      graph_data [list of GraphData]: return list of GraphData Object
    """


@register_object("graph_serialize.GraphData")
class GraphData(ObjectBase):
    """GraphData Object"""

    @staticmethod
    def create(g: DGLGraph):
        """Create GraphData"""
        # TODO(zihao): support serialize batched graph in the future.
        assert g.batch_size == 1, "Batched DGLGraph is not supported for serialization"
        ghandle = g._graph
        if len(g.ndata) != 0:
            node_tensors = dict()
            for key, value in g.ndata.items():
                node_tensors[key] = F.zerocopy_to_dgl_ndarray(value)
        else:
            node_tensors = None

        if len(g.edata) != 0:
            edge_tensors = dict()
            for key, value in g.edata.items():
                edge_tensors[key] = F.zerocopy_to_dgl_ndarray(value)
        else:
            edge_tensors = None

        return _CAPI_MakeGraphData(ghandle, node_tensors, edge_tensors)

    def get_graph(self):
        """Get DGLGraph from GraphData"""
        ghandle = _CAPI_GDataGraphHandle(self)
        g = DGLGraph(graph_data=ghandle, readonly=True)
        node_tensors_items = _CAPI_GDataNodeTensors(self).items()
        edge_tensors_items = _CAPI_GDataEdgeTensors(self).items()
        for k, v in node_tensors_items:
            g.ndata[k] = F.zerocopy_from_dgl_ndarray(v)
        for k, v in edge_tensors_items:
            g.edata[k] = F.zerocopy_from_dgl_ndarray(v)
        return g


def save_graphs(filename, g_list, labels=None):
    r"""
    Save DGLGraphs/DGLHeteroGraph and graph labels to file

    Parameters
    ----------
    filename : str
        File name to store graphs.
    g_list: list
        DGLGraph or list of DGLGraph/DGLHeteroGraph
    labels: dict[str, tensor]
        labels should be dict of tensors, with str as keys

    Examples
    ----------
    >>> import dgl
    >>> import torch as th

    Create :code:`DGLGraph`/:code:`DGLHeteroGraph` objects and initialize node
    and edge features.

    >>> g1 = dgl.graph(([0, 1, 2], [1, 2, 3])
    >>> g2 = dgl.graph(([0, 2], [2, 3])
    >>> g2.edata["e"] = th.ones(2, 4)

    Save Graphs into file

    >>> from dgl.data.utils import save_graphs
    >>> graph_labels = {"glabel": th.tensor([0, 1])}
    >>> save_graphs("./data.bin", [g1, g2], graph_labels)

    """
    # if it is local file, do some sanity check
    if filename.startswith('s3://') is False:
        assert not os.path.isdir(filename), "filename {} is an existing directory.".format(filename)
        f_path, _ = os.path.split(filename)
        if not os.path.exists(f_path):
            os.makedirs(f_path)

    g_sample = g_list[0] if isinstance(g_list, list) else g_list
    if isinstance(g_sample, DGLGraph):
        save_dglgraphs(filename, g_list, labels)
    elif isinstance(g_sample, DGLHeteroGraph):
        save_heterographs(filename, g_list, labels)
    else:
        raise Exception(
            "Invalid argument g_list. Must be a DGLGraph or a list of DGLGraphs/DGLHeteroGraphs")


def save_dglgraphs(filename, g_list, labels=None):
    """Internal function to save DGLGraphs"""
    if isinstance(g_list, DGLGraph):
        g_list = [g_list]
    if (labels is not None) and (len(labels) != 0):
        label_dict = dict()
        for key, value in labels.items():
            label_dict[key] = F.zerocopy_to_dgl_ndarray(value)
    else:
        label_dict = None
    gdata_list = [GraphData.create(g) for g in g_list]
    _CAPI_SaveDGLGraphs_V0(filename, gdata_list, label_dict)


def load_graphs(filename, idx_list=None):
    """
    Load DGLGraphs from file

    Parameters
    ----------
    filename: str
        filename to load graphs
    idx_list: list of int
        list of index of graph to be loaded. If not specified, will
        load all graphs from file

    Returns
    --------
    graph_list: list of DGLGraphs / DGLHeteroGraph
        The loaded graphs.
    labels: dict[str, Tensor]
        The graph labels stored in file. If no label is stored, the dictionary is empty.
        Regardless of whether the ``idx_list`` argument is given or not, the returned dictionary
        always contains labels of all the graphs.

    Examples
    ----------
    Following the example in save_graphs.

    >>> from dgl.data.utils import load_graphs
    >>> glist, label_dict = load_graphs("./data.bin") # glist will be [g1, g2]
    >>> glist, label_dict = load_graphs("./data.bin", [0]) # glist will be [g1]

    """
    # if it is local file, do some sanity check
    assert filename.startswith('s3://') or os.path.exists(filename), "file {} does not exist.".format(filename)

    version = _CAPI_GetFileVersion(filename)
    if version == 1:
        return load_graph_v1(filename, idx_list)
    elif version == 2:
        return load_graph_v2(filename, idx_list)
    else:
        raise Exception("Invalid DGL Version Number")


def load_graph_v2(filename, idx_list=None):
    """Internal functions for loading DGLHeteroGraphs."""
    if idx_list is None:
        idx_list = []
    assert isinstance(idx_list, list)
    heterograph_list = _CAPI_LoadGraphFiles_V2(filename, idx_list)
    label_dict = load_labels_v2(filename)
    return [gdata.get_graph() for gdata in heterograph_list], label_dict


def load_graph_v1(filename, idx_list=None):
    """"Internal functions for loading DGLGraphs (V0)."""
    if idx_list is None:
        idx_list = []
    assert isinstance(idx_list, list)
    metadata = _CAPI_LoadGraphFiles_V1(filename, idx_list, False)
    label_dict = {}
    for k, v in metadata.labels.items():
        label_dict[k] = F.zerocopy_from_dgl_ndarray(v)

    return [gdata.get_graph() for gdata in metadata.graph_data], label_dict


def load_labels(filename):
    """
    Load label dict from file

    Parameters
    ----------
    filename: str
        filename to load DGLGraphs

    Returns
    ----------
    labels: dict
        dict of labels stored in file (empty dict returned if no
        label stored)

    Examples
    ----------
    Following the example in save_graphs.

    >>> from dgl.data.utils import load_labels
    >>> label_dict = load_graphs("./data.bin")

    """
    # if it is local file, do some sanity check
    assert filename.startswith('s3://') or os.path.exists(filename), "file {} does not exist.".format(filename)

    version = _CAPI_GetFileVersion(filename)
    if version == 1:
        return load_labels_v1(filename)
    elif version == 2:
        return load_labels_v2(filename)
    else:
        raise Exception("Invalid DGL Version Number")


def load_labels_v2(filename):
    """Internal functions for loading labels from V2 format"""
    label_dict = {}
    nd_dict = _CAPI_LoadLabels_V2(filename)
    for k, v in nd_dict.items():
        label_dict[k] = F.zerocopy_from_dgl_ndarray(v)
    return label_dict


def load_labels_v1(filename):
    """Internal functions for loading labels from V1 format"""
    metadata = _CAPI_LoadGraphFiles_V1(filename, [], True)
    label_dict = {}
    for k, v in metadata.labels.items():
        label_dict[k] = F.zerocopy_from_dgl_ndarray(v)
    return label_dict
