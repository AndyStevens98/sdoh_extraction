import logging
import os
import string
from collections import Counter, OrderedDict

import pandas as pd

from config.constants import (
    ARGUMENTS,
    ATTRIBUTE,
    ENTITIES,
    EVENT,
    EVENTS,
    RELATION,
    RELATIONS,
    TEXTBOUND,
    TRIGGER,
)
from corpus.brat import (
    Attribute,
    Textbound,
    get_annotations,
    get_max_id,
    get_next_index,
    get_unique_arg,
    write_ann,
    write_txt,
)
from corpus.document import Document
from corpus.labels import brat2events, tb2entities, tb2relations
from corpus.tokenization import remove_white_space_at_ends
from spert_utils.spert_io import doc2spert, doc2spert_multi

#from spert_utils.convert_brat import


def ids_to_keep(event_dict, tb_dict, event_types=None, argument_types=None):


    event_ids_keep = set([])
    tb_ids_keep = set([])

    # iterate over events
    for event_id, event in event_dict.items():

        # iterate over arguments in current event, including trigger
        for arg_role, tb_id in event.arguments.items():

            # get text bound for current argument
            tb = tb_dict[tb_id]

            # check for event and argument type equivalence
            event_type_match =    (event_types is None) or    (event.type_ in event_types)
            argument_type_match = (argument_types is None) or (tb.type_ in argument_types)

            # collect ids if match
            if event_type_match and argument_type_match:
                event_ids_keep.add(event_id)
                tb_ids_keep.add(tb_id)

    return (event_ids_keep, tb_ids_keep)


def non_white_space_check(x, y):
    x = "".join(x.split())
    y = "".join(y.split())
    assert x == y, '''"{}" vs "{}"'''.format(x, y)


def get_line(index, text):
    return  1 + text[:index].count('\n')

def find_tb_not_in_events(tb_dict, event_dict, text, id, annotator,
                                message = 'Argument not connected to an event'):


    # get a set of all tb in events
    tb_in_events = set([tb_id for event in event_dict.values() \
                        for tb_id in event.arguments.values()])

    # find tb not included in events
    not_found = []
    for tb_id, tb in tb_dict.items():
        if tb_id not in tb_in_events:
            not_found.append(tb_id)


    output = []
    for tb_id in not_found:
        tb = tb_dict[tb_id]
        line_number = get_line(tb.start, text)
        output.append((annotator, id, line_number, tb.type_, tb.text, message))

    return output

def find_missing_arguments(tb_dict, event_dict, text, required_arguments, id, annotator,
                                message = 'Event is missing required argument'):

    output = []
    for event in event_dict.values():
        if event.type_ in required_arguments:
            _, tb_id = event.get_trigger()
            tb = tb_dict[tb_id]
            line_number = get_line(tb.start, text)
            for argument in required_arguments[event.type_]:
                if argument not in event.arguments:
                    output.append((annotator, id, line_number, argument, '--', message))

    return output


def find_missing_labels(tb_dict, attr_dict, text, labeled_arguments, id, annotator,
                                message = 'Argument missing a label'):
    if labeled_arguments is None:
        return []

    not_found = []
    for tb_id, tb in tb_dict.items():
        if (tb.type_ in labeled_arguments) and (tb_id not in attr_dict):
            not_found.append(tb_id)

    output = []
    for tb_id in not_found:
        tb = tb_dict[tb_id]
        line_number = get_line(tb.start, text)
        output.append((annotator, id, line_number, tb.type_, tb.text, message))

    return output

def tokenize_document(text, tokenizer):

    doc = tokenizer(text)

    # get sentences
    sentences = list(doc.sents)

    # remove empty sentences
    sentences = [sent for sent in sentences if sent.text.strip()]

    # iterate over sentences
    tokens = []
    offsets = []
    for sent in sentences:

        # get non whitespace tokens
        sent = [t for t in sent if t.text.strip()]

        # get tokens
        tokens.append([t.text for t in sent])

        # get token offsets
        offsets.append([(t.idx, t.idx + len(t.text)) for t in sent])

    # Check
    assert len(tokens) == len(offsets)
    for tok, off in zip(tokens, offsets):
        assert len(tok) == len(off)
        for t, o in zip(tok, off):
            assert t == text[o[0]:o[1]]

    return (tokens, offsets)


def adj_tokens(tokens, offsets, by_sent=True):

    if (tokens is None) or by_sent:
        return (tokens, offsets)


    else:

        assert len(tokens) == len(offsets)

        tokens_out = []
        offsets_out = []
        for token, offset in zip(tokens, offsets):

            assert len(token) == len(offset)

            for tok, off in zip(token, offset):
                tokens_out.append(tok)
                offsets_out.append(off)

        return (tokens_out, offsets_out)


class DocumentBrat(Document):


    def __init__(self, \
        id,
        text,
        ann = None,
        tags = None,
        tokenizer = None,
        event_dict = None,
        relation_dict = None,
        tb_dict = None,
        attr_dict = None,
        ):

        Document.__init__(self, \
            id = id,
            text = text,
            tags = tags,
            )

        if tokenizer is None:
            self.indices, self.token_offsets = None, None
        else:
            self.tokens, self.token_offsets = tokenize_document(text, tokenizer)


        self.ann = ann

        if ann is not None:

            assert event_dict is None
            assert relation_dict is None
            assert tb_dict is None
            assert attr_dict is None

            # Extract events, text bounds, and attributes from annotation string
            self.event_dict, self.relation_dict, self.tb_dict, self.attr_dict = get_annotations(ann)

        else:
            assert event_dict is not None
            assert relation_dict is not None
            assert tb_dict is not None
            assert attr_dict is not None

            self.event_dict = event_dict
            self.relation_dict = relation_dict
            self.tb_dict = tb_dict
            self.attr_dict = attr_dict


    def sentence_count(self):
        return len(self.tokens)

    def word_count(self):
        return sum([len(sent) for sent in self.tokens])

    def entities(self, as_dict=False, by_sent=False, entity_types=None):
        '''
        get list of entities for document
        '''

        entities = tb2entities(self.tb_dict, self.attr_dict, \
                                            as_dict = as_dict,
                                            tokens = self.tokens,
                                            token_offsets = self.token_offsets,
                                            by_sent = by_sent)

        if entity_types is not None:
            entities = [entity for entity in entities if entity.type_ in entity_types]

        return entities

    def relations(self, by_sent=False, entity_types=None):
        '''
        get list of relations for document
        '''



        relations = tb2relations(self.relation_dict, self.tb_dict, self.attr_dict, \
                                            tokens = self.tokens,
                                            token_offsets = self.token_offsets,
                                            by_sent = by_sent)

        if entity_types is not None:
            relations = [relation for relation in relations if \
                                (relation.entity_a.type_ in entity_types) and
                                (relation.entity_b.type_ in entity_types)]

        return relations

    def events(self, by_sent=False, event_types=None, entity_types=None):
        '''
        get list of entities for document
        '''


        events = brat2events(self.event_dict, self.tb_dict, self.attr_dict, \
                                    tokens = self.tokens,
                                    token_offsets = self.token_offsets,
                                    by_sent = by_sent)

        if event_types is not None:

            # filter by event types
            events = [event for event in events if \
                        (event_types is None) or (event.type_ in event_types)]

        if entity_types is not None:


            # filter arguments
            for event in events:
                event.arguments = [arg for arg in event.arguments if \
                        (entity_types is None) or (arg.type_ in entity_types)]

        return events

    def events2spert(self, event_types=None, entity_types=None,
                    skip_duplicate_spans=True, include_doc_text=False):

        spert_doc, entity_counter, relation_counter = doc2spert(self, \
                            event_types = event_types,
                            entity_types = entity_types,
                            skip_duplicate_spans = skip_duplicate_spans,
                            include_doc_text = include_doc_text)

        return (spert_doc, entity_counter, relation_counter)

    def events2spert_multi(self, \
                    event_types,
                    entity_types,
                    subtype_layers,
                    subtype_default,
                    skip_duplicate_spans = True,
                    include_doc_text = False):

        spert_doc, entity_counter, relation_counter = doc2spert_multi( \
                            doc = self,
                            event_types = event_types,
                            entity_types = entity_types,
                            subtype_layers = subtype_layers,
                            subtype_default = subtype_default,
                            skip_duplicate_spans = skip_duplicate_spans,
                            include_doc_text = include_doc_text)

        return (spert_doc, entity_counter, relation_counter)

    def y(self):
        y = OrderedDict()
        y[ENTITIES] = self.entities()
        y[RELATIONS] = self.relations()
        y[EVENTS] = self.events()
        return y


    def Xy(self):
        return (self.X(), self.y())

    def brat_str(self, event_types=None, argument_types=None):



        event_ids_keep, tb_ids_keep = ids_to_keep( \
                                event_dict = self.event_dict,
                                tb_dict = self.tb_dict,
                                event_types = event_types,
                                argument_types = argument_types)


        ann = []

        for tb_id, tb in self.tb_dict.items():
            if tb_id in tb_ids_keep:
                ann.append(tb.brat_str())

        for _, x in self.relation_dict.items():
            ann.append(x.brat_str())

        for event_id, event in self.event_dict.items():
            if event_id in event_ids_keep:
                ann.append(event.brat_str(tb_ids_keep=tb_ids_keep))

        for tb_id, attr in self.attr_dict.items():
            if tb_id in tb_ids_keep:
                ann.append(attr.brat_str())

        ann = "\n".join(ann)

        return ann

    def write_brat(self, path, event_types=None, argument_types=None):

        fn_text = write_txt(path, self.id, self.text)

        ann = self.brat_str( \
                    event_types = event_types,
                    argument_types = argument_types)

        fn_ann = write_ann(path, self.id, ann)

        return (fn_text, fn_ann)

    def quality_check(self, annotator_position=None, labeled_arguments=None,
                    required_arguments=None):
        rows = []

        if annotator_position is None:
            annotator = "unknown"
        else:
            annotator = self.id.split(os.sep)[annotator_position]

        r = find_tb_not_in_events( \
                        tb_dict = self.tb_dict,
                        event_dict = self.event_dict,
                        text = self.text,
                        id = self.id,
                        annotator = annotator)
        rows.extend(r)

        r = find_missing_labels( \
                        tb_dict = self.tb_dict,
                        attr_dict = self.attr_dict,
                        text = self.text,
                        labeled_arguments = labeled_arguments,
                        id = self.id,
                        annotator = annotator)
        rows.extend(r)

        r = find_missing_arguments( \
                        tb_dict = self.tb_dict,
                        event_dict = self.event_dict,
                        text = self.text,
                        required_arguments = required_arguments,
                        id = self.id,
                        annotator = annotator)
        rows.extend(r)

        columns = ["annotator", "id", "line", "argument", "text", "message"]
        df = pd.DataFrame(rows, columns=columns)

        return df

    def annotation_summary(self):


        counter = Counter()
        counter[EVENT] += len(self.event_dict)
        counter[RELATION] += len(self.relation_dict)
        counter[TEXTBOUND] += len(self.tb_dict)
        counter[ATTRIBUTE] += len(self.attr_dict)

        return counter

    def label_summary(self):


        y = self.y()

        counters = OrderedDict()
        counters[ENTITIES] = Counter()
        counters[RELATIONS] = Counter()
        counters[EVENTS] = Counter()

        for annotation_type, annotations in y.items():
            for a in annotations:

                if annotation_type == ENTITIES:
                    k = (a.type_, a.subtype)
                    counters[ENTITIES][k] += 1

                elif annotation_type == RELATIONS:
                    k = (a.entity_a.type_, a.entity_b.type_, a.role)
                    counters[RELATIONS][k] += 1

                elif annotation_type == EVENTS:
                    for arg in a.arguments:
                        k = (a.type_, arg.type_, arg.subtype)
                        counters[EVENTS][k] += 1

                else:
                    raise ValueError(f"Invalid annotation type: {annotation_type}")

        return counters


    def snap_textbounds(self):
        '''
        Snap the textbound indices to the starts and ends of the associated tokens.
        This is intended to correct annotation errors where only a partial word is annotated.
        '''
        offsets = self.token_offsets()

        text = self.text()

        for id, tb in self.tb_dict.items():

            _, start_tb, end_tb = \
                        remove_white_space_at_ends(tb.text, tb.start, tb.end)


            # Adjust start
            start_new = None
            for _, start, end in offsets:
                if (start_tb >= start) and (start_tb < end):
                    start_new = start
                    break

            # Adjust end
            end_new = None
            for _, start, end in offsets:
                if (end_tb > start) and (end_tb <= end):
                    end_new = end
                    break

            if (start_new is None) or (end_new is None):
                raise ValueError(f"Could not map textbound:\n{tb}\n{text}")

            if (tb.start != start_new) or (tb.end != end_new):

                text_new = text[start_new:end_new]

                tb.start = start_new
                tb.end = end_new
                tb.text = text_new

                assert self.tb_dict[id].text == text_new

        return True

    def map_(self, event_map=None, relation_map=None, tb_map=None, attr_map=None):
        '''
        Map document argument types, span types, and span labels
        '''

        counter = Counter()
        if event_map is not None:
            # Map events types
            # Loop on mapping
            for old, new_ in event_map.items():

                # Loop on events in document
                for id_, evt in self.event_dict.items():

                    # Update type, if match
                    if evt.type_ == old:
                        evt.type_ = new_
                        counter[(EVENTS, old, new_)] += 1


        if relation_map is not None:
            NotImplementedError("Need to update to provide relation mapping")


        if tb_map is not None:

            # Map text bound types
            # Loop on mapping
            for old, new_ in tb_map.items():

                # Loop on text bounds in document
                for id_, tb in self.tb_dict.items():

                    # Update type, if match
                    if tb.type_ == old:
                        tb.type_ = new_
                        counter[(TEXTBOUND, old, new_)] += 1

                # Loop on events in document
                for id_, evt in self.event_dict.items():

                    # Loop on arguments in event
                    new_args = OrderedDict()
                    for arg_type, tb in evt.arguments.items():

                        if arg_type == old:
                            new_args[new_] = tb
                            counter[(ARGUMENTS, old, new_)] += 1
                        else:
                            new_args[arg_type] = tb

                    # Assign mapped arguments
                    evt.arguments = new_args


        if attr_map is not None:
            # Map attribute names
            # Loop on mapping
            for old, new_ in attr_map.items():

                # Loop on attributes in document
                for id_, attr in self.attr_dict.items():

                    # Update type, if match
                    if attr.type_ == old:
                        attr.type_ = new_
                        counter[(ATTRIBUTE, old, new_)] += 1

        return counter

    def map_roles(self, role_map):
        '''
        Map document argument types, span types, and span labels
        '''

        counter = Counter()

        # iterate over events in document
        for event_id, event in self.event_dict.items():

            # initialize new argument dictionary
            new_arguments = OrderedDict()

            # iterate over arguments
            for role, tb_id in event.arguments.items():

                # update role name, if applicable
                role_lookup = role.rstrip(string.digits)
                if role_lookup in role_map:
                    role = role_map[role_lookup]
                    role = get_unique_arg(role, new_arguments)
                    counter[(role_lookup, role)] += 1

                new_arguments[role] = tb_id

            # update event arguments
            event.arguments = new_arguments

        return counter


    def swap_spans(self, source, target, use_role=True):
        '''
        Replace span for argument source with span from argument target
        '''

        # iterate over events
        counter = Counter()

        tb_index = get_next_index(self.tb_dict)
        attr_index = get_next_index(self.attr_dict)

        tb_to_remove = set([])

        for event_id, event in self.event_dict.items():

            # Replace argument target with trigger, if applicable
            trigger_type, _ = event.get_trigger()
            if target == TRIGGER:
                target_temp = trigger_type
            else:
                target_temp = target

            source_tb_id = None
            target_tb_id = None
            role = None

            # source and target are the role names in the event
            if use_role:

                # get text bound ids
                if source in event.arguments:
                    source_tb_id = event.arguments[source]

                if target_temp in event.arguments:
                    target_tb_id = event.arguments[target_temp]

                role = source

            # source and target are the argument names in the event
            else:

                # need to get add the textbound types (argument names)
                for role_name, tb_id in event.arguments.items():
                    tb = self.tb_dict[tb_id]

                    if source == tb.type_:
                        source_tb_id = tb_id
                        role = role_name

                    if target_temp == tb.type_:
                        target_tb_id = tb_id

            # replace span if both source and target present
            if (source_tb_id is not None) and (target_tb_id is not None):

                assert role is not None

                # get text bounds (object)
                source_tb = self.tb_dict[source_tb_id]
                target_tb = self.tb_dict[target_tb_id]

                new_tb_id = f'T{tb_index}'
                tb_index += 1

                new_tb = Textbound( \
                                id =     new_tb_id,
                                type_ =  source_tb.type_,
                                start =  target_tb.start,
                                end =    target_tb.end,
                                text =   target_tb.text,
                                tokens = target_tb.tokens,
                                )
                self.tb_dict[new_tb_id] = new_tb
                event.arguments[role] = new_tb_id

                counter['new_tb'] += 1

                # keep list of tb to remove
                tb_to_remove.add(source_tb_id)

                if source_tb_id in self.attr_dict:
                    source_attr = self.attr_dict[source_tb_id]

                    new_attr_id = f'A{attr_index}'
                    attr_index += 1

                    new_attr = Attribute( \
                                id =        new_attr_id,
                                type_ =     source_attr.type_,
                                textbound = new_tb_id,
                                value =     source_attr.value)
                    self.attr_dict[new_tb_id] = new_attr

                    counter['new_attr'] += 1

        for tb_id in tb_to_remove:
            del self.tb_dict[tb_id]
            counter['rm_tb'] += 1
            if tb_id in self.attr_dict:
                del self.attr_dict[tb_id]
                counter['rm_attr'] += 1


        return counter

    def transfer_subtype_value(self, argument_pairs):

        assert isinstance(argument_pairs, dict)

        # iterate over source - target arguments type pairs
        counts = Counter()
        for target_arg, source_arg in argument_pairs.items():

            # iterate over all events in document
            for event_id, event in self.event_dict.items():

                # to get dictionary map between argument types and textbound ids
                arguments = event.arguments
                arg_type_to_tb_id = OrderedDict()
                for arg_role, tb_id in arguments.items():
                    arg_type = self.tb_dict[tb_id].type_
                    arg_type_to_tb_id[arg_type] = tb_id

                # check if both the source and target are present
                if (source_arg in arg_type_to_tb_id) and \
                   (target_arg in arg_type_to_tb_id):

                    source_tb = arg_type_to_tb_id[source_arg]
                    target_tb = arg_type_to_tb_id[target_arg]

                    # determine if attribute defined for source
                    if source_tb in self.attr_dict:

                        source_attr = self.attr_dict[source_tb]
                        source_value = source_attr.value

                        attr_id = get_max_id(self.attr_dict)+1
                        attr_id = f"A{attr_id}"

                        attr_ob = Attribute( \
                                id =        attr_id,
                                type_ =     target_arg,
                                textbound = target_tb,
                                value =     source_value)

                        if target_tb in self.attr_dict:
                            logging.warn(f"target text bound in attr_dict: {target_tb} in {self.attr_dict.keys()}")
                        self.attr_dict[target_tb] = attr_ob

                        counts[(target_arg, source_value)] += 1

        return counts

    def prune_invalid_connections(self, args_by_event_type):

        event_ids = list(self.event_dict.keys())
        for id in event_ids:
            event = self.event_dict[id]
            if event.type_ not in args_by_event_type:
                del self.event_dict[id]

        # counts = Counter()
        # for _, event in self.event_dict.items():
        #
        #     arg_types = list(event.arguments.keys())[1:]
        #
        #     for arg_type in arg_types:
        #
        #         arg_type_strip = arg_type.rstrip(string.digits)
        #
        #         if arg_type_strip not in args_by_event_type[event.type_]:
        #             counts[(event.type_, arg_type_strip)] += 1
        #             del event.arguments[arg_type]

        counts = Counter()
        for _, event in self.event_dict.items():

            # find invalid roles
            to_remove = []
            for i, (role, tb_id) in enumerate(event.arguments.items()):

                if i > 0:
                    tb = self.tb_dict[tb_id]
                    if tb.type_ not in args_by_event_type[event.type_]:
                        to_remove.append(role)

            # remove invalid roles
            for role in to_remove:
                del event.arguments[role]

        return counts




# def tokenize_document_OLD(text, tokenizer):
#
#     doc = tokenizer(text)
#
#     #sent_bounds = []
#     tokens = []
#     offsets = []
#     for t in doc:
#         if not t.text.isspace():
#             tokens.append(t.text)
#             offsets.append((t.idx, t.idx + len(t.text)))
#
#     # Check
#     for tok, off in zip(tokens, offsets):
#         assert tok == text[off[0]:off[1]]
#
#
#     return (tokens, offsets)
