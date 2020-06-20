import copy
import re
import sys


class FixAction:
  def __init__(self, raw, rule, always_generate_new_ids = False):
     self._raw = raw
     self._rule_name = rule.NAME
     self._rule_lineno = rule._lineno
     self._always_gen_id = always_generate_new_ids
     #
     self._additions = 0
     self._exclusions = 0
     self._copy_leaves = 0
     #
     self._split_camel_re = re.compile(r"([a-z])([A-Z])")
     #
     self._action = None
     self._action = self.parse(self._raw)
     if self._additions > 0 and self._exclusions > 0:
       print("%s has add and exclude operations at the same time. skipping" % self, file=sys.stderr)
       self._action = None
     if not self._action:
       self._additions = 0
       self._exclusions = 0
       self._copy_leaves = 0

  def __bool__(self):
    return self._action is not None

  def __repr__(self):
    if self._action is None:
      return str(None)
    return "action: %s of %s at %s" % (
      self._raw, self._rule_name, self._rule_lineno
    )

  def parse(self, raw):
    out = []
    raw_splitted = raw.split("/")
    possible_leaf = raw_splitted[-1]
    for p in raw_splitted:
      if p.strip() == "" or p == "-":
        out.append({ "action": "exclude" })
        self._exclusions += 1
        continue
      action = "rename"
      if p[0] == "+":
        action = "add"
        p = p[1:]
        self._additions += 1
      elif p[0] == "!":
        action = "copy_leaf"
        if id(p) != id(possible_leaf):
          self._action = False
          print("copy_leaf(!) used not with leaf in %s" % (self), file=sys.stderr)
          return None
        p = p[1:]
        self._copy_leaves += 1
      _type, *quals = p.replace(":",",").split(",")
      _type = _type.strip()
      if _type == "":
        print("empty type for %s" % (self), file=sys.stderr)
        return None
      quals = dict([ (kv+"=").split("=")[0:2] for kv in quals if kv ])
      out.append({
        "action" : action,
        "type" : _type,
        "quals" : quals,
        "depth" : len(out) + 1,
      })
    return out or None

  def act(self, ctx, nodes_data):
    """
      copy node if updating parentctx:
        if adding or changing parentctx (skipping)
        remove/set _ISLEAF when needed
      return dict added nodes {id(node):id}
      mark removed/updated leaves as {id(node):none}
      mark leaves as to be removed from old leaves
    """
    if ctx is None:
      return None
    if self._action is None:
      return None
    fulltag = ctx.get("_FULLTAG")
    depth = ctx.get("_DEPTH")
    if depth != self.active_depth():
      print("unbalanced number of tag %s and actions %s. skipping" % (fulltag, self), file = sys.stderr)
      return None
    # no mixed add & remove rules yet
    if self.action_types_num() > 1:
      print("too many action types for %s and action %s. skipping" %(fulltag, self), file = sys.stderr)
      return None

    # run substitutions on original nodes
    re_ctx = ctx.get("_RECTX") and ctx["_RECTX"].groupdict() or None
    self.run_subsitutions(ctx, re_ctx)

    new_nodes = {}
    # remove
    if self._exclusions > 0:
      self.run_exclusions(ctx, new_nodes)
      return new_nodes

    # copy leaves first
    if self._copy_leaves > 0:
      self.run_copy_leaves(ctx, new_nodes, re_ctx)
    # add
    if self._additions > 0:
      new_leaves = list(new_nodes.values())
      for node in [ ctx ] + new_leaves:
        self.run_additions(node, new_nodes, nodes_data)
      return new_nodes
    #
    return new_nodes

  def run_copy_leaves(self, ctx, new_nodes, re_ctx):
    prev, it = None, ctx
    for ait in reversed(self._action):
      is_leaf = it.get("_ISLEAF", False)
      parent = it.get("_PARENTCTX")
      #
      if ait["action"] == "copy_leaf":
        if is_leaf:
          # copy node, keep leaf, add link to the source group
          it = self.copy_node(it, new_nodes, keep_leaf = True, clean = True)
          self.update_node(it, ait, re_ctx)
        #
      # copy only leaf, so
      break
      #
      prev, it = it, parent
      continue
    return

  def run_additions(self, ctx, new_nodes, nodes_data):
    # are different length allowed?
    # original and current iterators
    oit, oprev = ctx, None
    it, prev = ctx, None
    for ait in reversed(self._action):
      aa, adepth = ait["action"], ait["depth"]

      oparent = it and it.get("_PARENTCTX") or None
      if ait["action"] != "add":
        # should we copy unused to chain?
        continue
      #
    #
    return

  def copy_action(self, action, gen_id = False, src_id = None, depth = 0, type = None):
    data = action.copy()
    data["quals"] = data.get("quals", {}).copy()
    if type: action["type"] = type
    if gen_id:
      data["quals"].update({ "ID" : self.new_id(src_id = src_id, depth = depth, type = action["type"]) })
    return data

  def copy_node(self, node, new_nodes, keep_leaf = False, clean = False, force = False, store_src_link = False):
    if not force and node.get("_ISCOPY"):
      return node
    ncopy = node.copy()
    ncopy["_COPIES_LINKS"] = None

    if store_src_link:
      if not node.get("_COPIES_LINKS"): node["_COPIES_LINKS"] = []
      node["_COPIES_LINKS"].append(ncopy)
      ncopy["_SRC_LINK"] = node

    old_rules_data = ncopy.get("_RULESDATA")
    if old_rules_data is not None:
      ncopy["_RULESDATA"] = copy.deepcopy(old_rules_data)
    ncopy["_ISCOPY"] = True
    new_nodes[id(ncopy)] = ncopy
    # clean
    if clean:
      ncopy.get("_RULESDATA")["_ALL"]["USEDQUALS"] = {}
    # mark old leaf as unused
    if not keep_leaf:
      self.del_node_if_leaf(node, new_nodes)
    return ncopy

  def copy_chain(self, chain_start, stop_at, new_nodes, keep_leaf = False):
    if chain_start is None: return None
    if stop_at is None: return None
    #
    it, prev = chain_start, None
    while it:
      cp = self.copy_node(it, new_nodes)
      if prev:
        prev["_PARENTCTX"] = cp
      else:
        cp["_ISLEAF"] = True
      if it == stop_at:
        it = cp
        break
      prev, it = cp, cp.get("_PARENTCTX")
    #
    if not it:
      return None
    return it

  def del_node_if_leaf(self, node, new_nodes):
    if node.get("_ISLEAF", False):
      if id(node) in new_nodes:
        new_nodes[id(node)]["_DELETED"] = True
      else:
        new_nodes[id(node)] = None

  def run_subsitutions(self, ctx, re_ctx=None):
    if ctx is None:
      return None
    if self._action is None:
      return None
    #
    it = ctx
    for ait in reversed(self._action):
      aa = ait["action"]
      if aa == "add":
        continue
      if aa == "rename":
        self.update_node(it, ait, re_ctx)
      #do nothing for exclude and copy_leaf
      it = it.get("_PARENTCTX")
    return

  def run_exclusions(self, ctx, new_nodes):
    prev, it = None, ctx
    chain_start = ctx
    for ait in reversed(self._action):
      is_leaf = it.get("_ISLEAF", False)
      parent = it.get("_PARENTCTX")
      #
      if ait["action"] == "exclude":
        if is_leaf:
          self.del_node_if_leaf(it, new_nodes)
          if parent:
            parent = self.copy_node(parent, new_nodes)
            parent["_ISLEAF"] = True
            chain_start = parent
        elif prev:
          #copy the whole chain
          prev = self.copy_chain(chain_start, prev, new_nodes)
          prev["_PARENTCTX"] = parent
        #
        prev, it = prev, parent
      else:
        prev, it = it, parent
    return

  def update_node(self, node, action, re_ctx = None):
    if not node or not action:
      return
    _type = self.from_rectx(action["type"], re_ctx)
    node["_TYPE"] = _type
    used_quals = node.get("_RULESDATA")["_ALL"].get("USEDQUALS")
    if used_quals is not None:
      for q, v in action.get("quals",{}).items():
        q = self.from_rectx(q, re_ctx)
        v = self.from_rectx(v, re_ctx)
        _q = q.lower()
        if _q in used_quals:
          if v is None or v == "":
            used_quals.pop(_q)
          else:
            tq, tv = used_quals[_q]
            used_quals[_q] = (tq, v)
        else:
          used_quals.update({_q:(q, v)})
    return

  @classmethod
  def update_id(cls, node, id):
    if not node:
      return
    node["_ID"] = id
    used_quals = node.get("_RULESDATA")["_ALL"].get("USEDQUALS")
    if used_quals is None:
      node.get("_RULESDATA")["_ALL"]["USEDQUALS"] = {}
      used_quals = node.get("_RULESDATA")["_ALL"].get("USEDQUALS")
    used_quals.update({"id":("ID", id)})

  def new_id(self, src_id = None, depth = 0, type = None):
    if depth < 0: depth  = 100 - depth
    _type = "df"
    if type:
      splitted_name = self._split_camel_re.sub(r"\1_\2", type).split("_")
      _type = "d" + "".join([s[0] for s in splitted_name if s])
    return "%s_%sd%s" % (src_id, _type.lower(), depth)

  def gen_and_update_id(self, it, parent = None, depth = 0, action = None):
    _id = it.get("_ID")
    if _id:
      return _id
    _src_id = parent and parent.get("_ID")
    if _src_id:
      _src_id = "%s_ch" % _src_id # child derived
    else:
      # use locus tag
      _src_id = "%s:%s_%s%s" % (it["_SEQID"], it["_START"], it["_END"], it["_STRAND"] != "1" and it["_STRAND"] or "")
    _type = action and action.get("type") or None
    _id = self.new_id(src_id = _src_id, depth = depth, type=_type)

    self.update_id(it, _id)

  def from_rectx(self, x, re_ctx=None):
    if not re_ctx or x is None: return x
    if type(x) != str or len(x) < 2: return x
    if x[0] == "@":
      x = x[1:]
      x = re_ctx.get(x, x)
    return x

  def active_depth(self):
    return len(self._action) - self._additions

  def action_types_num(self):
    actions = [ self ]
    _w_ex = len(list(filter(lambda a: a._exclusions > 0, actions)))
    _w_add = len(list(filter(lambda a: a._additions > 0, actions)))
    # ignore copy leaves here
    actions_types_num = sum([
        _w_ex > 0,
        _w_add > 0,
        (len(actions) - _w_ex - _w_add) > 0,
    ])
    return actions_types_num