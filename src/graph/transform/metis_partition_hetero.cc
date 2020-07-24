/*!
 *  Copyright (c) 2020 by Contributors
 * \file graph/metis_partition.cc
 * \brief Call Metis partitioning
 */

#include <dgl/base_heterograph.h>
#include <dgl/packed_func_ext.h>
#include <metis.h>

#include "../heterograph.h"
#include "../unit_graph.h"

using namespace dgl::runtime;

namespace dgl {

namespace transform {

IdArray MetisPartition(UnitGraphPtr g, int k, NDArray vwgt_arr) {
  // The index type of Metis needs to be compatible with DGL index type.
  CHECK_EQ(sizeof(idx_t), sizeof(int64_t))
    << "Metis only supports int64 graph for now";
  // This is a symmetric graph, so in-csr and out-csr are the same.
  const auto mat = g->GetCSRMatrix(0);
  //   const auto mat = g->GetInCSR()->ToCSRMatrix();

  idx_t nvtxs = g->NumVertices(0);
  idx_t ncon = 1;  // # balacing constraints.
  idx_t *xadj = static_cast<idx_t *>(mat.indptr->data);
  idx_t *adjncy = static_cast<idx_t *>(mat.indices->data);
  idx_t nparts = k;
  IdArray part_arr = aten::NewIdArray(nvtxs);
  idx_t objval = 0;
  idx_t *part = static_cast<idx_t *>(part_arr->data);

  int64_t vwgt_len = vwgt_arr->shape[0];
  CHECK_EQ(sizeof(idx_t), vwgt_arr->dtype.bits / 8)
    << "The vertex weight array doesn't have right type";
  CHECK(vwgt_len % g->NumVertices(0) == 0)
    << "The vertex weight array doesn't have right number of elements";
  idx_t *vwgt = NULL;
  if (vwgt_len > 0) {
    ncon = vwgt_len / g->NumVertices(0);
    vwgt = static_cast<idx_t *>(vwgt_arr->data);
  }

  idx_t options[METIS_NOPTIONS];
  METIS_SetDefaultOptions(options);
  options[METIS_OPTION_ONDISK] = 1;

  int ret = METIS_PartGraphKway(
    &nvtxs,  // The number of vertices
    &ncon,   // The number of balancing constraints.
    xadj,    // indptr
    adjncy,  // indices
    vwgt,    // the weights of the vertices
    NULL,    // The size of the vertices for computing
    // the total communication volume
    NULL,     // The weights of the edges
    &nparts,  // The number of partitions.
    NULL,     // the desired weight for each partition and constraint
    NULL,     // the allowed load imbalance tolerance
    options,  // the array of options
    &objval,  // the edge-cut or the total communication volume of
    // the partitioning solution
    part);
  LOG(INFO) << "Partition a graph with " << g->NumVertices(0) << " nodes and "
            << g->NumEdges(0) << " edges into " << k << " parts and get "
            << objval << " edge cuts";
  switch (ret) {
    case METIS_OK:
      return part_arr;
    case METIS_ERROR_INPUT:
      LOG(FATAL) << "Error in Metis partitioning: input error";
    case METIS_ERROR_MEMORY:
      LOG(FATAL) << "Error in Metis partitioning: cannot allocate memory";
    default:
      LOG(FATAL) << "Error in Metis partitioning: other errors";
  }
  // return an array of 0 elements to indicate the error.
  return aten::NullArray();
}

DGL_REGISTER_GLOBAL("partition._CAPI_DGLMetisPartition_Hetero")
  .set_body([](DGLArgs args, DGLRetValue *rv) {
    HeteroGraphRef g = args[0];
    auto hgptr = std::dynamic_pointer_cast<HeteroGraph>(g.sptr());
    CHECK(hgptr) << "Invalid HeteroGraph object";
    CHECK_EQ(hgptr->relation_graphs().size(), 1)
      << "Metis partition only supports HomoGraph";
    auto ugptr = hgptr->relation_graphs()[0];
    int k = args[1];
    NDArray vwgt = args[2];
    *rv = MetisPartition(ugptr, k, vwgt);
  });
}  // namespace transform
}  // namespace dgl
